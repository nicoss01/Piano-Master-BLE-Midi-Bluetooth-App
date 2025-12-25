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
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

CONFIG_FILE = "piano_config.json"

# --- UTILITAIRES MUSIQUE ---
NOTE_NAMES = ['Do', 'Do#', 'Ré', 'Ré#', 'Mi', 'Fa', 'Fa#', 'Sol', 'Sol#', 'La', 'La#', 'Si']

def get_note_name(note_number):
    """Convertit 60 en 'Do4'"""
    octave = note_number // 12 - 1
    name = NOTE_NAMES[note_number % 12]
    return f"{name}{octave}"

class BluetoothManager:
    """Gère la connexion Bluetooth Low Energy."""
    def __init__(self, loop):
        self.client = None
        self.loop = loop
        self.device_address = None
        self.device_name = None
        self.midi_uuid = None
        self.is_connected = False
        self.write_type = "write-without-response" # Par défaut
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
        if device:
            self.device_address = device.address
            self.device_name = device.name
        if uuid:
            self.midi_uuid = uuid

        if not self.device_address:
            raise Exception("Aucune adresse configurée.")

        print(f"Connexion à {self.device_address}...")
        self.client = BleakClient(self.device_address)
        await self.client.connect()
        
        # On redétecte toujours pour être sûr d'avoir le bon mode d'écriture
        await self.find_write_characteristic()
            
        self.is_connected = True
        self.save_config()
        return True

    async def find_write_characteristic(self):
        # 1. Priorité absolue : Write Without Response (Fluide)
        for service in self.client.services:
            for char in service.characteristics:
                if "write-without-response" in char.properties:
                    self.midi_uuid = char.uuid
                    self.write_type = "write-without-response"
                    print(f"✅ Mode optimisé trouvé (No Response) : {self.midi_uuid}")
                    return
        
        # 2. Fallback : Write Standard (Peut bloquer)
        for service in self.client.services:
            for char in service.characteristics:
                if "write" in char.properties:
                    self.midi_uuid = char.uuid
                    self.write_type = "write"
                    print(f"⚠️ Mode standard trouvé (With Response) : {self.midi_uuid}")
                    return
        raise Exception("Aucune caractéristique d'écriture trouvée.")

    async def send_midi(self, data):
        if self.is_connected and self.client and self.midi_uuid:
            try:
                # BLE MIDI Packet: Header + Timestamp + Data
                packet = bytearray([0x80, 0x80] + list(data))
                # On spécifie explicitement si on veut une réponse ou non
                use_response = (self.write_type == "write")
                await self.client.write_gatt_char(self.midi_uuid, packet, response=use_response)
            except Exception as e:
                print(f"Erreur envoi: {e}")

    async def send_reset(self):
        """Envoie 'All Notes Off' pour couper le son."""
        if not self.is_connected: return
        print("🔇 Réinitialisation du son...")
        # Envoie CC 123 (All Notes Off) sur les 16 canaux MIDI
        for ch in range(16):
            # [Status (CC | channel), Control (123), Value (0)]
            await self.send_midi([0xB0 | ch, 123, 0])

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.is_connected = False

class PianoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Initialisation Logic ---
        self.loop = asyncio.new_event_loop()
        self.bt_thread = threading.Thread(target=self.start_loop, daemon=True)
        self.bt_thread.start()
        
        self.bt_manager = BluetoothManager(self.loop)
        
        # État Lecteur
        self.current_midi_file = None
        self.is_playing = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.rewind_event = threading.Event() 
        self.playback_speed = 1.0
        self.loop_playback = False
        
        # Données de visualisation
        self.midi_duration = 0
        self.pixels_per_second = 80  # Augmenté pour plus de lisibilité
        self.key_height = 0 

        # --- Interface Graphique ---
        self.title("Piano Bluetooth Master")
        self.geometry("1200x850")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.setup_sidebar()
        self.setup_main_area()
        
        # Auto-connexion
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

    # --- UI SETUP ---
    def setup_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="🎹 Piano Master", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # Status
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
        self.main_frame = ctk.CTkFrame(self, corner_radius=20)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1) 

        # 1. Infos Fichier & Notes
        self.info_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.info_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        
        self.lbl_filename = ctk.CTkLabel(self.info_frame, text="Aucun fichier chargé", font=("Arial", 16))
        self.lbl_filename.pack(side="left")
        
        self.lbl_current_notes = ctk.CTkLabel(self.info_frame, text="-", font=("Arial", 18, "bold"), text_color="#E07A5F")
        self.lbl_current_notes.pack(side="right")

        # 2. Visualisation (Piano Roll Amélioré)
        self.canvas_frame = ctk.CTkFrame(self.main_frame)
        self.canvas_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=5)
        
        # Fond sombre pour contraste
        self.piano_roll = ctk.CTkCanvas(self.canvas_frame, bg="#1a1a1a", highlightthickness=0)
        self.piano_roll.pack(fill="both", expand=True)
        
        # Curseur de lecture
        self.playhead_x = 100 # Décalé un peu vers la droite pour voir ce qui arrive
        self.piano_roll.create_line(self.playhead_x, 0, self.playhead_x, 2000, fill="#FF5555", width=2, tags="playhead")

        # 3. Progression
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.set(0)
        
        self.lbl_time = ctk.CTkLabel(self.progress_frame, text="00:00 / 00:00")
        self.lbl_time.pack()

        # 4. Contrôles
        self.controls_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.controls_frame.grid(row=3, column=0, pady=20)

        # Vitesse
        ctk.CTkLabel(self.controls_frame, text="Vitesse:").pack(side="left", padx=5)
        self.slider_speed = ctk.CTkSlider(self.controls_frame, from_=0.2, to=2.0, width=100, command=self.update_speed_label)
        self.slider_speed.set(1.0)
        self.slider_speed.pack(side="left", padx=5)
        self.lbl_speed_val = ctk.CTkLabel(self.controls_frame, text="x1.0", width=30)
        self.lbl_speed_val.pack(side="left", padx=5)

        # Boutons lecture
        ctk.CTkButton(self.controls_frame, text="⏮", width=40, command=self.rewind).pack(side="left", padx=20)
        self.btn_play = ctk.CTkButton(self.controls_frame, text="▶ Lecture", width=120, height=40, font=("Arial", 15, "bold"), command=self.toggle_play)
        self.btn_play.pack(side="left", padx=10)
        self.btn_loop = ctk.CTkCheckBox(self.controls_frame, text="Répéter", command=self.toggle_loop)
        self.btn_loop.pack(side="left", padx=10)

        # 5. Logs
        self.log_box = ctk.CTkTextbox(self.main_frame, height=100)
        self.log_box.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

    # --- VISUALISATION LOGIC ---
    def draw_background_grid(self, total_width, canvas_height):
        """Dessine le fond type 'Piano' (Touches noires/blanches)."""
        # On redessine les bandes horizontales
        for i in range(88): # 88 touches
            note_idx = i + 21 # MIDI note start at 21 (A0)
            y_pos = (87 - i) * self.key_height
            
            # Couleur alternée pour simuler un clavier
            # Touches noires: 1, 3, 6, 8, 10 (C# D# F# G# A#) dans l'octave
            is_black = (note_idx % 12) in [1, 3, 6, 8, 10]
            
            bg_color = "#2b2b2b" if is_black else "#333333"
            self.piano_roll.create_rectangle(0, y_pos, total_width, y_pos + self.key_height, 
                                             fill=bg_color, outline="", tags="grid")
            
            # Ligne de séparation fine
            self.piano_roll.create_line(0, y_pos, total_width, y_pos, fill="#444", width=1, tags="grid")

            # Label Note (Do / C) pour se repérer
            if (note_idx % 12) == 0: # C / Do
                octave = (note_idx // 12) - 1
                self.piano_roll.create_text(15, y_pos + self.key_height/2, text=f"C{octave}", 
                                            fill="#888", font=("Arial", 8), anchor="w", tags="grid_label")

    def draw_midi_on_canvas(self, filepath):
        """Pré-analyse le fichier MIDI pour dessiner le Piano Roll."""
        self.piano_roll.delete("note")
        self.piano_roll.delete("grid")
        self.piano_roll.delete("grid_label")
        
        try:
            mid = mido.MidiFile(filepath)
            
            events = []
            active_notes = {}
            current_time = 0.0
            
            for msg in mido.merge_tracks(mid.tracks):
                current_time += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes[msg.note] = current_time
                elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in active_notes:
                        start = active_notes.pop(msg.note)
                        duration = current_time - start
                        events.append((start, duration, msg.note))
            
            self.midi_duration = current_time
            
            # Échelle Y
            canvas_height = 500 # Plus grand pour lisibilité
            self.key_height = canvas_height / 88
            
            # Scroll Region
            total_width = (self.midi_duration * self.pixels_per_second) + 400
            self.piano_roll.configure(scrollregion=(0, 0, total_width, canvas_height))
            
            # 1. Dessiner le fond (Clavier)
            self.draw_background_grid(total_width, canvas_height)
            
            # 2. Dessiner les notes
            for start, duration, note in events:
                x0 = (start * self.pixels_per_second) + self.playhead_x
                x1 = x0 + (duration * self.pixels_per_second)
                # Inversion Y : 21 en bas, 108 en haut
                # index 0 (bas) = note 21
                # index 87 (haut) = note 108
                # y = (87 - (note - 21)) * h
                row_index = note - 21
                if row_index < 0 or row_index > 87: continue # Hors clavier 88 touches
                
                y_pos = (87 - row_index) * self.key_height 
                
                # Couleur: Bleu pour tout le monde, ou différencié
                color = "#4dabf7" # Bleu clair lisible
                # Contour noir pour bien séparer les notes
                self.piano_roll.create_rectangle(x0, y_pos, x1, y_pos + self.key_height - 1, 
                                                 fill=color, outline="black", width=1, tags="note")

        except Exception as e:
            self.log(f"Erreur dessin partition: {e}")

    def update_canvas_view(self, current_time):
        """Déplace la vue du canvas."""
        target_x = (current_time * self.pixels_per_second)
        total_width = (self.midi_duration * self.pixels_per_second) + 400
        if total_width > 0:
            fraction = target_x / total_width
            self.piano_roll.xview_moveto(fraction)

    def show_active_notes_on_canvas(self, active_notes):
        """Affiche un feedback visuel sur le piano roll pour les notes actives."""
        self.piano_roll.delete("active_overlay")
        
        for note_num in active_notes:
            row_index = note_num - 21
            if row_index < 0 or row_index > 87: continue

            note_name = get_note_name(note_num)
            y_pos = (87 - row_index) * self.key_height
            
            # Ligne horizontale surbrillante sur toute la vue
            # self.piano_roll.create_line(0, y_pos + self.key_height/2, 20000, y_pos + self.key_height/2, 
            #                            fill="#ffffff", width=1, stipple="gray50", tags="active_overlay")

            # Indicateur sur le playhead
            self.piano_roll.create_oval(self.playhead_x - 6, y_pos, self.playhead_x + 6, y_pos + self.key_height, 
                                        fill="#e03131", outline="white", width=2, tags="active_overlay")
            
            # Nom de la note flottant
            self.piano_roll.create_text(self.playhead_x + 20, y_pos + (self.key_height/2), 
                                        text=note_name, fill="white", anchor="w", font=("Arial", 10, "bold"), 
                                        tags="active_overlay")
            
    def update_ui_components(self, current_time, total_duration, active_note_names):
         try:
            self.progress_bar.set(current_time / total_duration if total_duration > 0 else 0)
            self.lbl_time.configure(text=f"{self.format_time(current_time)} / {self.format_time(total_duration)}")
            self.lbl_current_notes.configure(text=" ".join(active_note_names[-5:]))
            self.update_canvas_view(current_time)
         except: pass

    # --- LOGIQUE GUI ---
    def log(self, message):
        self.log_box.insert("end", f"> {message}\n")
        self.log_box.see("end")

    def update_connection_ui(self, connected):
        if connected:
            self.status_indicator.configure(text_color="#2CC985")
            self.status_text.configure(text="Connecté")
            self.btn_connect.configure(text="Déconnecter", fg_color="#555")
        else:
            self.status_indicator.configure(text_color="red")
            self.status_text.configure(text="Déconnecté")
            self.btn_connect.configure(text="Connecter Piano", fg_color="#3B8ED0")

    def update_speed_label(self, value):
        self.playback_speed = float(value)
        self.lbl_speed_val.configure(text=f"x{self.playback_speed:.1f}")

    def toggle_loop(self):
        self.loop_playback = bool(self.btn_loop.get())

    # --- BLUETOOTH ---
    def open_connect_dialog(self):
        if self.bt_manager.is_connected:
            self.run_async(self.bt_manager.disconnect(), lambda _: self.update_connection_ui(False))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Appareils Bluetooth")
        dialog.geometry("400x350")
        dialog.attributes("-topmost", True)
        
        lbl = ctk.CTkLabel(dialog, text="Recherche en cours...")
        lbl.pack(pady=10)
        scroll = ctk.CTkScrollableFrame(dialog, width=350, height=250)
        scroll.pack(pady=5)

        def connect_to(device):
            lbl.configure(text=f"Connexion à {device.name}...")
            self.run_async(self.bt_manager.connect(device=device), self.on_connect_success, self.on_connect_fail)
            dialog.destroy()

        async def scan():
            devices = await BleakScanner.discover()
            lbl.configure(text=f"{len(devices)} appareils trouvés.")
            for d in devices:
                name = d.name or "Inconnu"
                col = "#2CC985" if any(x in name.lower() for x in ["piano", "midi"]) else "#555"
                ctk.CTkButton(scroll, text=f"{name}\n{d.address}", fg_color=col, 
                              command=lambda dev=d: connect_to(dev)).pack(pady=2, fill="x")

        self.run_async(scan())

    def on_connect_success(self, res):
        self.update_connection_ui(True)
        self.log(f"Connecté à {self.bt_manager.device_name}")

    def on_connect_fail(self, err):
        self.update_connection_ui(False)
        self.log(f"Erreur connexion : {err}")
        messagebox.showerror("Erreur", str(err))

    # --- MIDI PLAYER ---
    def load_midi_file(self):
        filename = filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid")])
        if filename:
            self.current_midi_file = filename
            self.lbl_filename.configure(text=os.path.basename(filename))
            self.log(f"Chargé : {os.path.basename(filename)}")
            
            # Reset son piano (All Notes Off)
            self.run_async(self.bt_manager.send_reset())

            # Générer la visualisation
            self.draw_midi_on_canvas(filename)
            self.stop_event.set()
            self.is_playing = False
            self.btn_play.configure(text="▶ Lecture")
            self.progress_bar.set(0)
            self.lbl_time.configure(text="00:00 / 00:00")

    def toggle_play(self):
        if not self.current_midi_file:
            return messagebox.showwarning("Info", "Chargez un fichier d'abord.")
        
        if not self.bt_manager.is_connected:
             if messagebox.askyesno("Info", "Piano non connecté. Continuer quand même ?") is False:
                 self.open_connect_dialog()
                 return
             else:
                 self.log("⚠️ Lecture en mode 'Offline' (Pas de son sur le piano)")

        if self.is_playing:
            self.is_paused = not self.is_paused
            self.btn_play.configure(text="▶ Reprendre" if self.is_paused else "⏸ Pause")
            self.log("Pause" if self.is_paused else "Reprise")
        else:
            self.is_playing = True
            self.is_paused = False
            self.stop_event.clear()
            self.rewind_event.clear()
            self.btn_play.configure(text="⏸ Pause")
            threading.Thread(target=self.play_midi_thread, daemon=True).start()

    def rewind(self):
        self.log("Rembobinage.")
        if self.is_playing:
            self.rewind_event.set()
        else:
            self.progress_bar.set(0)
            self.lbl_time.configure(text="00:00 / 00:00")
            self.piano_roll.xview_moveto(0)
            self.lbl_current_notes.configure(text="-")
            self.piano_roll.delete("active_overlay")
            self.run_async(self.bt_manager.send_reset())

    def format_time(self, t):
        return f"{int(t//60):02}:{int(t%60):02}"

    def play_midi_thread(self):
        try:
            self.log("▶ Début de la lecture...")
            mid = mido.MidiFile(self.current_midi_file)
            total_duration = mid.length
            merged = mido.merge_tracks(mid.tracks)
            
            active_notes_indices = set()
            active_note_names = []
            
            while True:
                # BOUCLE DE LECTURE MANUELLE (Pour gérer la vitesse)
                current_time = 0.0
                last_msg_time = 0.0
                
                # Reset UI
                self.after(0, lambda: self.update_ui_components(0, total_duration, []))
                
                for msg in merged:
                    if self.stop_event.is_set(): 
                        return

                    # --- GESTION REMBOBINAGE ---
                    if self.rewind_event.is_set():
                        self.log("⏪ Rembobinage...")
                        self.rewind_event.clear()
                        asyncio.run_coroutine_threadsafe(self.bt_manager.send_reset(), self.loop)
                        break 

                    # --- GESTION PAUSE ---
                    while self.is_paused:
                        if self.stop_event.is_set(): return
                        if self.rewind_event.is_set(): break
                        time.sleep(0.1)
                    
                    if self.rewind_event.is_set(): # Check post-pause
                        self.log("⏪ Rembobinage...")
                        self.rewind_event.clear()
                        asyncio.run_coroutine_threadsafe(self.bt_manager.send_reset(), self.loop)
                        break

                    # --- GESTION DU TEMPS (VITESSE) ---
                    # msg.time est le delta time. On doit attendre (delta / vitesse)
                    if msg.time > 0:
                        delay = msg.time / self.playback_speed
                        
                        # Attente fractionnée pour rester réactif
                        start_wait = time.time()
                        while time.time() - start_wait < delay:
                            if self.stop_event.is_set() or self.rewind_event.is_set(): break
                            time.sleep(min(0.01, delay)) # Sleep court
                        
                        current_time += msg.time
                        
                        # Update UI
                        self.after(0, lambda t=current_time: self.update_ui_components(t, total_duration, active_note_names))

                    # --- ENVOI & VISUALISATION ---
                    if not msg.is_meta:
                        future = asyncio.run_coroutine_threadsafe(self.bt_manager.send_midi(msg.bytes()), self.loop)
                        # Pas d'attente forcée ici pour garder la fluidité avec la gestion manuelle du temps
                        
                        # Visualisation
                        if msg.type == 'note_on' and msg.velocity > 0:
                            name = get_note_name(msg.note)
                            active_notes_indices.add(msg.note)
                            if name not in active_note_names:
                                active_note_names.append(name)
                        elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                            name = get_note_name(msg.note)
                            if msg.note in active_notes_indices:
                                active_notes_indices.remove(msg.note)
                            if name in active_note_names:
                                active_note_names.remove(name)
                        
                        # Update Visuel Canvas (Notes actives)
                        curr_set = list(active_notes_indices)
                        self.after(0, lambda n=curr_set: self.show_active_notes_on_canvas(n))

                if self.stop_event.is_set():
                    break
                
                if not self.loop_playback:
                    break
                
                self.log("Recommencement (Boucle)...")
                time.sleep(1)

        except Exception as e:
            self.log(f"❌ Erreur lecture: {e}")
        finally:
            self.is_playing = False
            self.after(0, lambda: self.btn_play.configure(text="▶ Lecture"))
            if not self.stop_event.is_set():
                self.log("Fin de lecture.")
                self.after(0, lambda: self.progress_bar.set(1))

if __name__ == "__main__":
    app = PianoApp()
    app.mainloop()