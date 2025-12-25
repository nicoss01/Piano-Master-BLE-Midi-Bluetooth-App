import asyncio
import threading
import os
import json
import time
from tkinter import filedialog, messagebox
import customtkinter as ctk  # pip install customtkinter
from bleak import BleakClient, BleakScanner
import mido

# --- CONFIGURATION GLOBALE ---
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

CONFIG_FILE = "piano_config.json"

# --- UTILITAIRES MUSIQUE ---
NOTE_NAMES = ['Do', 'Do#', 'Ré', 'Ré#', 'Mi', 'Fa', 'Fa#', 'Sol', 'Sol#', 'La', 'La#', 'Si']

def get_note_name(note_number):
    """Convertit 60 en 'Do4'"""
    octave = note_number // 12 - 1
    name = NOTE_NAMES[note_number % 12]
    return f"{name}{octave}"

def get_staff_position(midi_note, clef="treble"):
    """Calcule la position verticale relative sur la portée."""
    # Mapping des degrés de la gamme C Majeur (ignorer altérations pour la hauteur visuelle)
    # C=0, D=1, E=2, F=3, G=4, A=5, B=6
    semitone_to_degree = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
    
    octave = midi_note // 12
    degree = semitone_to_degree[midi_note % 12]
    
    # Position absolue en "degrés" depuis C0
    abs_pos = (octave * 7) + degree
    
    if clef == "treble":
        # Clé de Sol : La ligne du bas (Mi4 / E4) est la référence ?
        # Standard : Sol4 (G4) est sur la 2ème ligne.
        # G4 (67) -> oct 4, deg 4 -> 28+4 = 32
        ref_pos = 32 
        # Si ref_pos est à Y=0, alors abs_pos est à -(abs-ref) * demi_espace
        return -(abs_pos - ref_pos) + 2 # +2 pour centrer sur la 2eme ligne
    else:
        # Clé de Fa : Fa3 (F3) sur la 4ème ligne (en partant du bas)
        # F3 (53) -> oct 3, deg 3 -> 21+3 = 24
        ref_pos = 24
        return -(abs_pos - ref_pos)

class BluetoothManager:
    def __init__(self, loop, input_callback=None):
        self.client = None
        self.loop = loop
        self.device_address = None
        self.device_name = None
        self.midi_uuid = None
        self.is_connected = False
        self.write_type = "write-without-response"
        self.input_callback = input_callback 
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.device_address = config.get('device_address')
                    self.device_name = config.get('device_name')
                    self.midi_uuid = config.get('midi_uuid')
            except: pass

    def save_config(self):
        config = {
            'device_address': self.device_address,
            'device_name': self.device_name,
            'midi_uuid': self.midi_uuid
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
        except: pass

    async def connect(self, device=None, uuid=None):
        # Si on passe un objet BLEDevice (découvert par scan), on l'utilise direct
        # C'est plus fiable que l'adresse seule sur certains OS
        connect_target = device if device else self.device_address
        
        if not connect_target:
            raise Exception("Aucun appareil spécifié.")

        if device:
            self.device_address = device.address
            self.device_name = device.name

        print(f"Connexion à {self.device_address}...")
        
        try:
            self.client = BleakClient(connect_target)
            await self.client.connect()
            
            # Petit délai pour laisser Windows/Mac découvrir les services
            await asyncio.sleep(1.0)
            
            await self.setup_characteristics()
            self.is_connected = True
            self.save_config()
            return True
        except Exception as e:
            self.is_connected = False
            raise e

    async def setup_characteristics(self):
        write_char = None
        notify_char = None
        
        if not self.client.services:
            # Force refresh si vide
            await self.client.get_services()

        for service in self.client.services:
            for char in service.characteristics:
                props = char.properties
                if "write-without-response" in props:
                    write_char = char
                    self.write_type = "write-without-response"
                elif "write" in props and not write_char:
                    write_char = char
                    self.write_type = "write"
                
                if "notify" in props:
                    notify_char = char

        if not write_char:
            raise Exception("Pas de caractéristique d'écriture MIDI trouvée.")
        
        self.midi_uuid = write_char.uuid
        print(f"✅ Write UUID: {self.midi_uuid} ({self.write_type})")

        if notify_char:
            try:
                await self.client.start_notify(notify_char.uuid, self._on_notification)
                print(f"👂 Listen UUID: {notify_char.uuid}")
            except Exception as e:
                print(f"⚠️ Erreur Listen: {e}")
        else:
            print("⚠️ Pas de UUID Listen trouvé (Mode One-Way).")

    def _on_notification(self, sender, data):
        if len(data) >= 3:
            # Recherche pattern Note On
            for i in range(len(data)-2):
                byte = data[i]
                if 0x90 <= byte <= 0x9F: 
                    note = data[i+1]
                    velocity = data[i+2]
                    if velocity > 0 and self.input_callback:
                        self.loop.call_soon_threadsafe(self.input_callback, note)

    async def send_midi(self, data):
        if self.is_connected and self.client:
            try:
                packet = bytearray([0x80, 0x80] + list(data))
                use_response = (self.write_type == "write")
                await self.client.write_gatt_char(self.midi_uuid, packet, response=use_response)
            except Exception as e:
                print(f"Erreur envoi: {e}")

    async def send_reset(self):
        if not self.is_connected: return
        try:
            for ch in range(16):
                await self.send_midi([0xB0 | ch, 123, 0])
        except: pass

    async def disconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
            except: pass
            self.is_connected = False

class PianoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.loop = asyncio.new_event_loop()
        self.bt_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.bt_thread.start()
        
        self.bt_manager = BluetoothManager(self.loop, input_callback=self.on_piano_input)
        
        self.current_midi_file = None
        self.is_playing = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.rewind_event = threading.Event()
        self.loop_playback = False
        self.playback_mode = ctk.StringVar(value="Lecture Simple")
        self.next_note_event = threading.Event()
        
        # Visualisation
        self.midi_duration = 0
        self.pixels_per_second = 100 # Vitesse de défilement visuel
        self.staff_spacing = 10 # Espace entre lignes
        
        self.title("Piano Bluetooth Master")
        self.geometry("1400x900")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.setup_sidebar()
        self.setup_main_area()
        
        # Tentative connexion auto
        if self.bt_manager.device_address:
            self.log("Tentative de reconnexion auto...")
            self.run_async(self.bt_manager.connect(), self.on_connect_success, self.on_connect_fail)

    def start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_async(self, coro, callback_success=None, callback_error=None):
        def wrapper():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                res = future.result()
                if callback_success: self.after(0, callback_success, res)
            except Exception as e:
                if callback_error: self.after(0, callback_error, e)
        threading.Thread(target=wrapper, daemon=True).start()

    def setup_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)
        
        ctk.CTkLabel(self.sidebar_frame, text="🎹 Piano Master", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.status_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.status_frame.grid(row=1, column=0, padx=20, pady=10)
        self.status_indicator = ctk.CTkLabel(self.status_frame, text="●", text_color="red", font=("Arial", 24))
        self.status_indicator.pack(side="left")
        self.status_text = ctk.CTkLabel(self.status_frame, text="Déconnecté")
        self.status_text.pack(side="left", padx=5)
        
        self.btn_connect = ctk.CTkButton(self.sidebar_frame, text="Connecter Piano", command=self.open_connect_dialog)
        self.btn_connect.grid(row=2, column=0, padx=20, pady=10)
        self.btn_load = ctk.CTkButton(self.sidebar_frame, text="Ouvrir Fichier MIDI", command=self.load_midi_file, fg_color="#E07A5F", hover_color="#C45A40")
        self.btn_load.grid(row=3, column=0, padx=20, pady=10)

    def setup_main_area(self):
        self.main_frame = ctk.CTkFrame(self, corner_radius=20, fg_color="#f5f5f5")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1) 

        self.info_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.info_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        self.lbl_filename = ctk.CTkLabel(self.info_frame, text="Partition vierge", font=("Arial", 16), text_color="#333")
        self.lbl_filename.pack(side="left")
        self.lbl_current_notes = ctk.CTkLabel(self.info_frame, text="-", font=("Arial", 18, "bold"), text_color="#3B8ED0")
        self.lbl_current_notes.pack(side="right")

        # --- PARTITION SCROLLABLE ---
        self.canvas_frame = ctk.CTkFrame(self.main_frame, fg_color="white", border_width=2, border_color="#ccc")
        self.canvas_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=5)
        
        self.sheet_music = ctk.CTkCanvas(self.canvas_frame, bg="white", highlightthickness=0)
        self.sheet_music.pack(fill="both", expand=True)
        
        # Barre de lecture (fixe visuellement au début, le fond bougera)
        # Mais ici on bouge le scroll, donc la barre avance en coordonnées absolues
        self.sheet_music.create_line(0, 0, 0, 2000, fill="#FF5555", width=2, tags="playhead")

        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, progress_color="#3B8ED0")
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.set(0)
        self.lbl_time = ctk.CTkLabel(self.progress_frame, text="00:00 / 00:00", text_color="#555")
        self.lbl_time.pack()

        # Contrôles
        self.controls_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.controls_frame.grid(row=3, column=0, pady=20)
        ctk.CTkLabel(self.controls_frame, text="Mode :", text_color="#333").pack(side="left", padx=5)
        self.mode_selector = ctk.CTkSegmentedButton(self.controls_frame, values=["Lecture Simple", "Note à Note"], variable=self.playback_mode)
        self.mode_selector.pack(side="left", padx=10)
        ctk.CTkButton(self.controls_frame, text="⏮", width=40, command=self.rewind, fg_color="#666").pack(side="left", padx=20)
        self.btn_play = ctk.CTkButton(self.controls_frame, text="▶ Lecture", width=120, height=40, font=("Arial", 15, "bold"), command=self.toggle_play)
        self.btn_play.pack(side="left", padx=10)
        self.btn_loop = ctk.CTkCheckBox(self.controls_frame, text="Répéter", command=self.toggle_loop, text_color="#333")
        self.btn_loop.pack(side="left", padx=10)

        # Logs
        self.log_box = ctk.CTkTextbox(self.main_frame, height=100, fg_color="#fff", text_color="#333", border_width=1)
        self.log_box.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

    # --- DESSIN PARTITION ---
    def draw_staves(self, total_width):
        """Dessine le système de portées (Grand Staff)."""
        self.sheet_music.delete("staff")
        
        # Constantes Y
        treble_y = 150 # Centre approximatif clé de Sol
        bass_y = 350   # Centre approximatif clé de Fa
        
        # Lignes horizontales (5 par portée)
        # Portée du haut (Sol)
        for i in range(-2, 3): # -2, -1, 0, 1, 2 autour du centre
            y = treble_y + (i * self.staff_spacing)
            self.sheet_music.create_line(0, y, total_width, y, fill="#333", width=1, tags="staff")
            
        # Portée du bas (Fa)
        for i in range(-2, 3):
            y = bass_y + (i * self.staff_spacing)
            self.sheet_music.create_line(0, y, total_width, y, fill="#333", width=1, tags="staff")
            
        # Barre de mesure initiale et accolade
        self.sheet_music.create_line(20, treble_y - 2*self.staff_spacing, 20, bass_y + 2*self.staff_spacing, width=3, fill="black", tags="staff_static")
        
        # Clés (Simulées par texte)
        self.sheet_music.create_text(35, treble_y, text="𝄞", font=("Times", 40), tags="staff_static")
        self.sheet_music.create_text(35, bass_y, text="𝄢", font=("Times", 40), tags="staff_static")

    def draw_note(self, x, midi_note, duration_px):
        """Dessine une note sur la portée appropriée."""
        # Découpage du clavier : Do Central (60)
        # >= 60 : Main droite (Haut)
        # < 60  : Main gauche (Bas)
        
        if midi_note >= 60:
            base_y = 150 # Centre Clé Sol
            offset = get_staff_position(midi_note, "treble")
        else:
            base_y = 350 # Centre Clé Fa
            offset = get_staff_position(midi_note, "bass")
            
        y = base_y + (offset * (self.staff_spacing / 2))
        
        # Couleur : Noir par défaut
        color = "black"
        
        # Dessin Note (Ovale)
        radius_x = 6
        radius_y = 5
        self.sheet_music.create_oval(x, y - radius_y, x + radius_x*2, y + radius_y, fill=color, tags="note")
        
        # Hampe (Stem)
        # Règle simple : Si note en haut de portée -> tige bas, sinon tige haut
        stem_len = 35
        if offset > 0: # Note basse sur la portée -> Tige haut
            stem_x = x + radius_x*2
            stem_y2 = y - stem_len
        else: # Note haute -> Tige bas
            stem_x = x
            stem_y2 = y + stem_len
            
        self.sheet_music.create_line(stem_x, y, stem_x, stem_y2, width=1.5, fill=color, tags="note")
        
        # Ledger Lines (Lignes supplémentaires)
        # Limites portée : base_y +/- 2*spacing
        top_line = base_y - 2*self.staff_spacing
        bot_line = base_y + 2*self.staff_spacing
        
        if y < top_line - 2: # Au dessus
            curr_y = top_line - self.staff_spacing
            while curr_y > y + 2:
                self.sheet_music.create_line(x-4, curr_y, x+radius_x*2+4, curr_y, width=1, tags="note")
                curr_y -= self.staff_spacing
        elif y > bot_line + 2: # En dessous
            curr_y = bot_line + self.staff_spacing
            while curr_y < y - 2:
                self.sheet_music.create_line(x-4, curr_y, x+radius_x*2+4, curr_y, width=1, tags="note")
                curr_y += self.staff_spacing
                
        # TODO: Dièse/Bémol si besoin (non implémenté graphiquement pour simplifier)

    def draw_midi_file(self, filepath):
        self.sheet_music.delete("note")
        self.sheet_music.delete("staff")
        self.sheet_music.delete("playhead")
        
        try:
            mid = mido.MidiFile(filepath)
            events = []
            current_time = 0.0
            
            # Pré-calcul
            for msg in mido.merge_tracks(mid.tracks):
                current_time += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    events.append({'t': current_time, 'n': msg.note})
            
            self.midi_duration = current_time
            # Largeur totale = temps * pixels_par_sec + marge
            total_width = (self.midi_duration * self.pixels_per_second) + 1000
            
            # Configurer le scroll
            self.sheet_music.configure(scrollregion=(0, 0, total_width, 600))
            
            # Dessiner le décor
            self.draw_staves(total_width)
            
            # Dessiner toutes les notes
            for evt in events:
                x = 100 + (evt['t'] * self.pixels_per_second)
                self.draw_note(x, evt['n'], 20) # 20px largeur défaut
                
            # Playhead au dessus
            self.sheet_music.create_line(100, 0, 100, 600, fill="#FF5555", width=2, tags="playhead")

        except Exception as e:
            self.log(f"Erreur dessin: {e}")

    def update_view(self, current_time):
        # Position X absolue de la tête de lecture
        x = 100 + (current_time * self.pixels_per_second)
        self.sheet_music.coords("playhead", x, 0, x, 600)
        
        # Auto-Scroll : Garder le playhead à 20% de l'écran gauche
        view_w = self.sheet_music.winfo_width()
        if view_w < 100: view_w = 800
        
        target_left = x - (view_w * 0.2)
        if target_left < 0: target_left = 0
        
        # ScrollTo
        bbox = self.sheet_music.bbox("all")
        if bbox:
            scroll_w = bbox[2]
            if scroll_w > 0:
                self.sheet_music.xview_moveto(target_left / scroll_w)

    def show_active_notes(self, active_list, x_now):
        self.sheet_music.delete("active")
        for note in active_list:
            # Main Droite (Vert) / Main Gauche (Orange)
            color = "#2CC985" if note >= 60 else "#FF8C00"
            
            if note >= 60:
                base_y = 150
                offset = get_staff_position(note, "treble")
            else:
                base_y = 350
                offset = get_staff_position(note, "bass")
            
            y = base_y + (offset * (self.staff_spacing / 2))
            
            # Surbrillance
            self.sheet_music.create_oval(x_now - 8, y - 8, x_now + 20, y + 8, outline=color, width=3, tags="active")

    # --- MOTEUR AUDIO ---
    def play_midi_thread(self):
        try:
            self.log("▶ Lecture...")
            mid = mido.MidiFile(self.current_midi_file)
            dur = mid.length
            
            active_notes = set() # Set d'entiers
            note_names = []      # Liste de noms
            
            msgs = list(mido.merge_tracks(mid.tracks))
            current_time = 0.0
            
            while True:
                self.after(0, lambda: self.update_ui(0, dur, "-"))
                mode = self.playback_mode.get()
                current_time = 0.0
                
                if mode == "Lecture Simple":
                    # Moteur Flux (Mid.play)
                    playback = mid.play(meta_messages=True)
                    for msg in playback:
                        if self.stop_event.is_set(): return
                        while self.is_paused:
                            if self.stop_event.is_set(): return
                            if self.rewind_event.is_set(): break
                            time.sleep(0.1)
                        if self.rewind_event.is_set(): break
                        
                        current_time += msg.time
                        
                        if not msg.is_meta:
                            # Synchro stricte
                            fut = asyncio.run_coroutine_threadsafe(self.bt_manager.send_midi(msg.bytes()), self.loop)
                            try: fut.result(timeout=1.0)
                            except: pass
                            
                            self.process_msg(msg, active_notes, note_names)
                            
                            # UI Update
                            x = 100 + (current_time * self.pixels_per_second)
                            act_copy = list(active_notes)
                            txt = " | ".join(note_names[-4:])
                            self.after(0, lambda t=current_time, tx=txt, a=act_copy, xx=x: 
                                       [self.update_ui(t, dur, tx), self.show_active_notes(a, xx)])

                else:
                    # Moteur Pas à Pas
                    for i, msg in enumerate(msgs):
                        if self.stop_event.is_set(): return
                        if self.rewind_event.is_set(): break
                        while self.is_paused:
                            if self.stop_event.is_set(): return
                            if self.rewind_event.is_set(): break
                            time.sleep(0.1)
                        if self.rewind_event.is_set(): break
                        
                        current_time += msg.time
                        
                        if not msg.is_meta:
                            asyncio.run_coroutine_threadsafe(self.bt_manager.send_midi(msg.bytes()), self.loop)
                            self.process_msg(msg, active_notes, note_names)
                            
                            # Peek notes suivantes
                            next_s = []
                            idx = i+1
                            while len(next_s)<3 and idx<len(msgs):
                                if msgs[idx].type=='note_on' and msgs[idx].velocity>0:
                                    next_s.append(get_note_name(msgs[idx].note))
                                idx+=1
                            
                            x = 100 + (current_time * self.pixels_per_second)
                            act_copy = list(active_notes)
                            txt = f"{' '.join(note_names) if note_names else '-'} >> {' '.join(next_s)}"
                            
                            self.after(0, lambda t=current_time, tx=txt, a=act_copy, xx=x: 
                                       [self.update_ui(t, dur, tx), self.show_active_notes(a, xx)])
                            
                            # Blocage
                            if msg.type == 'note_on' and msg.velocity > 0:
                                self.next_note_event.clear()
                                self.log(f"🎹 Jouez: {get_note_name(msg.note)}")
                                while not self.next_note_event.is_set():
                                    if self.stop_event.is_set() or self.rewind_event.is_set(): break
                                    time.sleep(0.05)

                if self.rewind_event.is_set():
                    self.log("⏪ Rembobinage...")
                    self.rewind_event.clear()
                    asyncio.run_coroutine_threadsafe(self.bt_manager.send_reset(), self.loop)
                    continue
                
                if self.stop_event.is_set() or not self.loop_playback: break
                self.log("Recommencement...")
                time.sleep(1)

        except Exception as e:
            self.log(f"Erreur Play: {e}")
        finally:
            self.is_playing = False
            self.after(0, lambda: self.btn_play.configure(text="▶ Lecture"))
            if not self.stop_event.is_set(): self.log("Fin.")

    def process_msg(self, msg, active_set, name_list):
        if msg.type == 'note_on' and msg.velocity > 0:
            self.log(f"ON: {get_note_name(msg.note)}")
            active_set.add(msg.note)
            n = get_note_name(msg.note)
            if n not in name_list: name_list.append(n)
        elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
            self.log(f"OFF: {get_note_name(msg.note)}")
            if msg.note in active_set: active_set.remove(msg.note)
            n = get_note_name(msg.note)
            if n in name_list: name_list.remove(n)

    def update_ui(self, t, dur, txt):
        try:
            self.progress_bar.set(t/dur if dur > 0 else 0)
            self.lbl_time.configure(text=f"{int(t)//60:02}:{int(t)%60:02}")
            self.lbl_current_notes.configure(text=txt)
            self.update_view(t)
        except: pass

    # --- UI & BT Events ---
    def on_piano_input(self, note):
        if self.is_playing and self.playback_mode.get() == "Note à Note":
            self.next_note_event.set()
    
    def log(self, msg):
        self.log_box.insert("end", f"> {msg}\n")
        self.log_box.see("end")
    
    def on_connect_success(self, res):
        self.update_connection_ui(True)
        self.log(f"Connecté à {self.bt_manager.device_name}")
    
    def on_connect_fail(self, err):
        self.update_connection_ui(False)
        self.log(f"Erreur: {err}")
    
    def update_connection_ui(self, connected):
        color = "#2CC985" if connected else "red"
        txt = "Connecté" if connected else "Déconnecté"
        self.status_indicator.configure(text_color=color)
        self.status_text.configure(text=txt)
        self.btn_connect.configure(text="Déconnecter" if connected else "Connecter Piano")

    def open_connect_dialog(self):
        if self.bt_manager.is_connected:
            self.run_async(self.bt_manager.disconnect(), lambda _: self.update_connection_ui(False))
            return
        d = ctk.CTkToplevel(self)
        d.geometry("400x300")
        d.transient(self) 
        d.grab_set() 
        d.focus_force() 
        
        ctk.CTkLabel(d, text="Recherche...").pack(pady=10)
        s = ctk.CTkScrollableFrame(d)
        s.pack(fill="both", expand=True)
        async def scan():
            devs = await BleakScanner.discover()
            for dev in devs:
                name = dev.name or "Inconnu"
                ctk.CTkButton(s, text=f"{name}\n{dev.address}", 
                              command=lambda device=dev: [d.destroy(), self.run_async(self.bt_manager.connect(device), self.on_connect_success, self.on_connect_fail)]).pack(pady=2)
        self.run_async(scan())

    def load_midi_file(self):
        f = filedialog.askopenfilename(filetypes=[("MIDI", "*.mid")])
        if f:
            self.current_midi_file = f
            self.lbl_filename.configure(text=os.path.basename(f))
            self.log(f"Chargé: {os.path.basename(f)}")
            self.run_async(self.bt_manager.send_reset())
            self.draw_midi_file(f)
            self.stop_event.set()
            self.is_playing = False
            self.btn_play.configure(text="▶ Lecture")

    def toggle_play(self):
        if not self.current_midi_file: return
        if self.is_playing:
            self.is_paused = not self.is_paused
            self.btn_play.configure(text="▶ Reprendre" if self.is_paused else "⏸ Pause")
        else:
            self.is_playing = True
            self.is_paused = False
            self.stop_event.clear()
            self.rewind_event.clear()
            self.btn_play.configure(text="⏸ Pause")
            threading.Thread(target=self.play_midi_thread, daemon=True).start()

    def rewind(self):
        if self.is_playing: self.rewind_event.set()
        else:
            self.update_ui(0, 0, "-")
            self.sheet_music.xview_moveto(0)
            self.run_async(self.bt_manager.send_reset())

    def toggle_loop(self):
        self.loop_playback = bool(self.btn_loop.get())

if __name__ == "__main__":
    app = PianoApp()
    app.mainloop()