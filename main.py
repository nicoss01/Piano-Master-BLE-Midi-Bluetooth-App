"""
Piano Bluetooth Master v3.0
Visualisation de partition corrigée pour piano deux mains
"""

import asyncio
import threading
import os
import json
import time
from tkinter import filedialog
import customtkinter as ctk
from bleak import BleakClient, BleakScanner
import mido

# --- CONFIGURATION ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

CONFIG_FILE = "piano_config.json"

# --- COULEURS ---
class Colors:
    BG_DARK = "#0D1117"
    BG_CARD = "#161B22"
    BG_ELEVATED = "#21262D"
    
    STAFF_LINE = "#4A5568"
    STAFF_BG = "#1A1F2A"
    
    NOTE_PAST = "#3D4450"
    NOTE_CURRENT = "#FBBF24"
    NOTE_FUTURE = "#60A5FA"
    
    ACCENT_PRIMARY = "#8B5CF6"
    ACCENT_SUCCESS = "#10B981"
    
    TEXT_PRIMARY = "#F0F6FC"
    TEXT_SECONDARY = "#8B949E"
    TEXT_MUTED = "#484F58"
    
    RIGHT_HAND = "#10B981"
    LEFT_HAND = "#F59E0B"
    PLAYHEAD = "#EF4444"

# --- UTILITAIRES MUSIQUE ---
NOTE_NAMES = ['Do', 'Do#', 'Ré', 'Ré#', 'Mi', 'Fa', 'Fa#', 'Sol', 'Sol#', 'La', 'La#', 'Si']

def get_note_name(note_number):
    octave = note_number // 12 - 1
    name = NOTE_NAMES[note_number % 12]
    return f"{name}{octave}"

def is_sharp(midi_note):
    return (midi_note % 12) in [1, 3, 6, 8, 10]

def note_to_staff_position(midi_note):
    """
    Convertit une note MIDI en position sur la portée.
    Retourne (position, clef) où position est le nombre de demi-interlignes
    depuis la ligne centrale de la portée concernée.
    
    Clé de Sol: ligne du milieu = Si4 (B4, MIDI 71)
    Clé de Fa: ligne du milieu = Ré3 (D3, MIDI 50)
    """
    # Table: pour chaque note dans l'octave, sa position relative (en lignes/interlignes)
    # Do=0, Ré=1, Mi=2, Fa=3, Sol=4, La=5, Si=6
    note_positions = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]  # dièses sur même ligne que naturelle
    
    octave = midi_note // 12
    note_in_octave = midi_note % 12
    
    # Position absolue depuis Do0
    absolute_pos = octave * 7 + note_positions[note_in_octave]
    
    # Choisir la clé selon la note
    if midi_note >= 60:  # Do4 et au-dessus -> Clé de Sol
        # Si4 (B4) = MIDI 71 -> octave 5, note 11 -> pos = 5*7 + 6 = 41
        # Si4 est sur la ligne du milieu (position 0)
        ref_pos = 5 * 7 + 6  # B4 = 41
        return (ref_pos - absolute_pos, "treble")
    else:  # Sous Do4 -> Clé de Fa
        # Ré3 (D3) = MIDI 50 -> octave 4, note 2 -> pos = 4*7 + 1 = 29
        ref_pos = 4 * 7 + 1  # D3 = 29
        return (ref_pos - absolute_pos, "bass")


class MidiEvent:
    def __init__(self, time, note, velocity, duration=0.5):
        self.time = time
        self.note = note
        self.velocity = velocity
        self.duration = duration
        
    @property
    def end_time(self):
        return self.time + self.duration
    
    @property
    def name(self):
        return get_note_name(self.note)
    
    @property
    def is_right_hand(self):
        return self.note >= 60


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
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({
                    'device_address': self.device_address,
                    'device_name': self.device_name,
                    'midi_uuid': self.midi_uuid
                }, f, indent=4)
        except: pass

    async def connect(self, device=None):
        connect_target = device if device else self.device_address
        if not connect_target:
            raise Exception("Aucun appareil spécifié.")

        if device:
            self.device_address = device.address
            self.device_name = device.name

        try:
            self.client = BleakClient(connect_target)
            await self.client.connect()
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
            raise Exception("Pas de caractéristique MIDI trouvée.")
        
        self.midi_uuid = write_char.uuid

        if notify_char:
            try:
                await self.client.start_notify(notify_char.uuid, self._on_notification)
            except: pass

    def _on_notification(self, sender, data):
        if len(data) >= 3:
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
            except: pass

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


class SheetMusicCanvas(ctk.CTkCanvas):
    """Canvas pour afficher la partition de piano (deux portées)"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=Colors.STAFF_BG, highlightthickness=0, **kwargs)
        
        # Configuration visuelle
        self.line_spacing = 14  # Espace entre les lignes de la portée
        self.pixels_per_second = 150  # Vitesse de défilement horizontal
        self.note_head_rx = 7  # Rayon horizontal de la tête de note
        self.note_head_ry = 5  # Rayon vertical
        self.margin_left = 80  # Marge pour clés
        self.playhead_x = 200  # Position fixe de la tête de lecture
        
        # Positions verticales des portées
        self.treble_center_y = 0  # Calculé dynamiquement
        self.bass_center_y = 0
        
        # Données MIDI
        self.events = []
        self.current_time = 0.0
        self.midi_duration = 0.0
        
        self.bind("<Configure>", self._on_configure)
    
    def _on_configure(self, event):
        """Recalcule les positions quand le canvas change de taille"""
        h = event.height
        # Portée du haut (clé de sol) à 30% de la hauteur
        self.treble_center_y = int(h * 0.30)
        # Portée du bas (clé de fa) à 70% de la hauteur
        self.bass_center_y = int(h * 0.70)
        self.redraw()
    
    def load_midi(self, filepath):
        """Charge un fichier MIDI"""
        self.events = []
        
        try:
            mid = mido.MidiFile(filepath)
            
            # Collecter note_on avec durées
            active_notes = {}  # (channel, note) -> (start_time, velocity)
            current_time = 0.0
            
            for msg in mido.merge_tracks(mid.tracks):
                current_time += msg.time
                
                if msg.type == 'note_on' and msg.velocity > 0:
                    key = (msg.channel, msg.note)
                    active_notes[key] = (current_time, msg.velocity)
                    
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    key = (msg.channel, msg.note)
                    if key in active_notes:
                        start_time, velocity = active_notes.pop(key)
                        duration = max(0.1, current_time - start_time)
                        self.events.append(MidiEvent(
                            time=start_time,
                            note=msg.note,
                            velocity=velocity,
                            duration=duration
                        ))
            
            # Trier par temps
            self.events.sort(key=lambda e: e.time)
            self.midi_duration = current_time
            self.current_time = 0
            self.redraw()
            
        except Exception as e:
            print(f"Erreur chargement MIDI: {e}")
    
    def time_to_x(self, event_time):
        """Convertit un temps en position X (relatif au temps courant)"""
        return self.playhead_x + (event_time - self.current_time) * self.pixels_per_second
    
    def note_to_y(self, midi_note):
        """Convertit une note MIDI en position Y sur la partition"""
        position, clef = note_to_staff_position(midi_note)
        
        if clef == "treble":
            base_y = self.treble_center_y
        else:
            base_y = self.bass_center_y
        
        # Chaque position = demi-interligne
        y = base_y - position * (self.line_spacing / 2)
        return y, clef
    
    def draw_staff_lines(self):
        """Dessine les lignes des deux portées"""
        width = self.winfo_width()
        if width < 10:
            width = 800
        
        # 5 lignes par portée
        for i in range(-2, 3):
            # Clé de sol
            y = self.treble_center_y + i * self.line_spacing
            self.create_line(0, y, width, y, fill=Colors.STAFF_LINE, width=1, tags="staff")
            
            # Clé de fa
            y = self.bass_center_y + i * self.line_spacing
            self.create_line(0, y, width, y, fill=Colors.STAFF_LINE, width=1, tags="staff")
        
        # Accolade et barre de début
        top = self.treble_center_y - 2 * self.line_spacing
        bottom = self.bass_center_y + 2 * self.line_spacing
        
        self.create_line(self.margin_left - 20, top, self.margin_left - 20, bottom, 
                        fill=Colors.TEXT_PRIMARY, width=2, tags="staff")
        
        # Clé de Sol (symbole Unicode)
        self.create_text(self.margin_left - 45, self.treble_center_y + 8, 
                        text="𝄞", font=("Times New Roman", 42), 
                        fill=Colors.TEXT_PRIMARY, anchor="w", tags="staff")
        
        # Clé de Fa
        self.create_text(self.margin_left - 45, self.bass_center_y - 5, 
                        text="𝄢", font=("Times New Roman", 38), 
                        fill=Colors.TEXT_PRIMARY, anchor="w", tags="staff")
    
    def draw_ledger_lines(self, x, y, clef):
        """Dessine les lignes supplémentaires si nécessaire"""
        if clef == "treble":
            staff_top = self.treble_center_y - 2 * self.line_spacing
            staff_bottom = self.treble_center_y + 2 * self.line_spacing
        else:
            staff_top = self.bass_center_y - 2 * self.line_spacing
            staff_bottom = self.bass_center_y + 2 * self.line_spacing
        
        line_width = self.note_head_rx * 2 + 8
        
        # Lignes au-dessus
        if y < staff_top - 2:
            ly = staff_top - self.line_spacing
            while ly >= y - 2:
                self.create_line(x - line_width/2, ly, x + line_width/2, ly,
                               fill=Colors.STAFF_LINE, width=1, tags="note")
                ly -= self.line_spacing
        
        # Lignes en-dessous
        if y > staff_bottom + 2:
            ly = staff_bottom + self.line_spacing
            while ly <= y + 2:
                self.create_line(x - line_width/2, ly, x + line_width/2, ly,
                               fill=Colors.STAFF_LINE, width=1, tags="note")
                ly += self.line_spacing
        
        # Ligne du Do central (entre les deux portées)
        middle_c_y = (self.treble_center_y + self.bass_center_y) / 2
        if abs(y - middle_c_y) < self.line_spacing / 2:
            self.create_line(x - line_width/2, middle_c_y, x + line_width/2, middle_c_y,
                           fill=Colors.STAFF_LINE, width=1, tags="note")
    
    def draw_note(self, event, state="future"):
        """Dessine une note sur la partition"""
        x = self.time_to_x(event.time)
        y, clef = self.note_to_y(event.note)
        
        # Couleur selon l'état
        if state == "past":
            color = Colors.NOTE_PAST
        elif state == "current":
            color = Colors.NOTE_CURRENT
        else:
            # Future: couleur selon la main
            color = Colors.RIGHT_HAND if event.is_right_hand else Colors.LEFT_HAND
        
        # Lignes supplémentaires
        self.draw_ledger_lines(x, y, clef)
        
        # Altération (dièse)
        if is_sharp(event.note):
            self.create_text(x - self.note_head_rx - 12, y, text="♯",
                           font=("Arial", 14), fill=color, tags="note")
        
        # Tête de note (ovale remplie pour noire/croche, vide pour blanche/ronde)
        rx, ry = self.note_head_rx, self.note_head_ry
        
        if event.duration >= 1.5:  # Ronde ou plus
            self.create_oval(x - rx, y - ry, x + rx, y + ry,
                           outline=color, width=2, tags="note")
        else:
            self.create_oval(x - rx, y - ry, x + rx, y + ry,
                           fill=color, outline=color, tags="note")
        
        # Hampe (pas pour les rondes)
        if event.duration < 3.0:
            stem_length = 35
            # Direction de la hampe selon la position sur la portée
            if clef == "treble":
                stem_up = y > self.treble_center_y
            else:
                stem_up = y > self.bass_center_y
            
            if stem_up:
                stem_x = x + rx - 1
                self.create_line(stem_x, y, stem_x, y - stem_length,
                               fill=color, width=1.5, tags="note")
            else:
                stem_x = x - rx + 1
                self.create_line(stem_x, y, stem_x, y + stem_length,
                               fill=color, width=1.5, tags="note")
        
        # Effet de surbrillance pour note courante
        if state == "current":
            self.create_oval(x - rx - 5, y - ry - 5, x + rx + 5, y + ry + 5,
                           outline=Colors.NOTE_CURRENT, width=2, tags="note")
            # Afficher le nom de la note
            self.create_text(x, y - ry - 15, text=event.name,
                           font=("Arial", 10, "bold"), fill=Colors.NOTE_CURRENT, tags="note")
    
    def draw_playhead(self):
        """Dessine la ligne de lecture verticale"""
        top = self.treble_center_y - 3 * self.line_spacing
        bottom = self.bass_center_y + 3 * self.line_spacing
        
        # Ligne rouge
        self.create_line(self.playhead_x, top, self.playhead_x, bottom,
                        fill=Colors.PLAYHEAD, width=2, tags="playhead")
        
        # Triangle en haut
        self.create_polygon(
            self.playhead_x - 8, top - 12,
            self.playhead_x + 8, top - 12,
            self.playhead_x, top - 2,
            fill=Colors.PLAYHEAD, tags="playhead"
        )
    
    def redraw(self):
        """Redessine toute la partition"""
        self.delete("all")
        
        width = self.winfo_width()
        if width < 10:
            return
        
        # Fond
        self.create_rectangle(0, 0, width, self.winfo_height(), 
                            fill=Colors.STAFF_BG, outline="", tags="bg")
        
        # Portées
        self.draw_staff_lines()
        
        # Calculer la plage de temps visible
        time_left = self.current_time - (self.playhead_x / self.pixels_per_second)
        time_right = self.current_time + ((width - self.playhead_x) / self.pixels_per_second)
        
        # Dessiner les notes visibles
        for event in self.events:
            # Filtrer les notes hors écran
            if event.time < time_left - 1 or event.time > time_right + 1:
                continue
            
            # Déterminer l'état de la note
            delta = event.time - self.current_time
            if delta < -0.05:
                state = "past"
            elif delta < 0.3:
                state = "current"
            else:
                state = "future"
            
            self.draw_note(event, state)
        
        # Tête de lecture
        self.draw_playhead()
    
    def update_time(self, t):
        """Met à jour le temps courant et redessine"""
        self.current_time = t
        self.redraw()
    
    def get_notes_at_time(self, t, tolerance=0.2):
        """Retourne les notes à jouer à un instant donné"""
        return [e for e in self.events if abs(e.time - t) < tolerance]


class MiniKeyboard(ctk.CTkCanvas):
    """Mini clavier de piano pour visualisation"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=Colors.BG_CARD, highlightthickness=0, height=70, **kwargs)
        
        self.active_notes = set()
        self.start_note = 36  # C2
        self.end_note = 96    # C7
        
        self.bind("<Configure>", lambda e: self.redraw())
    
    def redraw(self):
        self.delete("all")
        
        width = self.winfo_width()
        height = self.winfo_height()
        
        if width < 50:
            return
        
        # Compter les touches blanches
        white_notes = [n for n in range(self.start_note, self.end_note + 1) if not is_sharp(n)]
        num_white = len(white_notes)
        
        key_width = width / num_white
        white_height = height - 5
        black_height = white_height * 0.6
        
        # Dessiner touches blanches
        x = 0
        white_x = {}
        for note in range(self.start_note, self.end_note + 1):
            if not is_sharp(note):
                is_active = note in self.active_notes
                color = Colors.ACCENT_SUCCESS if is_active else "#E8E8E8"
                self.create_rectangle(x, 5, x + key_width - 1, white_height,
                                     fill=color, outline="#888", width=1)
                white_x[note] = x
                
                # Marquer Do central
                if note == 60:
                    self.create_oval(x + key_width/2 - 3, white_height - 12,
                                   x + key_width/2 + 3, white_height - 6,
                                   fill=Colors.ACCENT_PRIMARY, outline="")
                x += key_width
        
        # Dessiner touches noires
        for note in range(self.start_note, self.end_note + 1):
            if is_sharp(note):
                prev_white = note - 1
                if prev_white in white_x:
                    bx = white_x[prev_white] + key_width * 0.7
                    bw = key_width * 0.6
                    is_active = note in self.active_notes
                    color = Colors.LEFT_HAND if is_active else "#1A1A2E"
                    self.create_rectangle(bx, 5, bx + bw, black_height,
                                         fill=color, outline="#333")
    
    def set_active(self, notes):
        self.active_notes = set(notes)
        self.redraw()
    
    def add_note(self, note):
        self.active_notes.add(note)
        self.redraw()
    
    def remove_note(self, note):
        self.active_notes.discard(note)
        self.redraw()


class PianoApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.loop = asyncio.new_event_loop()
        self.bt_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.bt_thread.start()
        
        self.bt_manager = BluetoothManager(self.loop, input_callback=self.on_piano_input)
        
        self.current_midi_file = None
        self.is_playing = False
        self.is_paused = False
        self.stop_event = threading.Event()
        self.rewind_event = threading.Event()
        self.loop_playback = False
        self.playback_mode = ctk.StringVar(value="simple")
        self.next_note_event = threading.Event()
        
        self.title("🎹 Piano Master")
        self.geometry("1400x850")
        self.configure(fg_color=Colors.BG_DARK)
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._setup_sidebar()
        self._setup_main()
        
        # Auto-reconnexion
        if self.bt_manager.device_address:
            self.log("🔄 Reconnexion...")
            self.run_async(self.bt_manager.connect(), self._on_connect_ok, self._on_connect_fail)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_async(self, coro, on_success=None, on_error=None):
        def wrapper():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                res = future.result()
                if on_success:
                    self.after(0, on_success, res)
            except Exception as e:
                if on_error:
                    self.after(0, on_error, e)
        threading.Thread(target=wrapper, daemon=True).start()

    def _setup_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color=Colors.BG_CARD)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        
        # Titre
        ctk.CTkLabel(sidebar, text="🎹 Piano Master",
                    font=ctk.CTkFont(size=22, weight="bold"),
                    text_color=Colors.TEXT_PRIMARY).pack(pady=(30, 5))
        
        ctk.CTkLabel(sidebar, text="Apprentissage MIDI Bluetooth",
                    font=ctk.CTkFont(size=11),
                    text_color=Colors.TEXT_SECONDARY).pack()
        
        # Statut
        status_frame = ctk.CTkFrame(sidebar, fg_color=Colors.BG_ELEVATED, corner_radius=10)
        status_frame.pack(pady=25, padx=20, fill="x")
        
        inner = ctk.CTkFrame(status_frame, fg_color="transparent")
        inner.pack(pady=12, padx=15, fill="x")
        
        self.status_dot = ctk.CTkLabel(inner, text="●", text_color="#EF4444", font=("Arial", 14))
        self.status_dot.pack(side="left")
        
        self.status_label = ctk.CTkLabel(inner, text="Déconnecté",
                                        font=ctk.CTkFont(size=13),
                                        text_color=Colors.TEXT_SECONDARY)
        self.status_label.pack(side="left", padx=8)
        
        self.device_label = ctk.CTkLabel(status_frame, text="Aucun appareil",
                                        font=ctk.CTkFont(size=10),
                                        text_color=Colors.TEXT_MUTED)
        self.device_label.pack(pady=(0, 10))
        
        # Boutons
        self.btn_connect = ctk.CTkButton(sidebar, text="Connecter Piano",
                                        font=ctk.CTkFont(size=14, weight="bold"),
                                        fg_color=Colors.ACCENT_PRIMARY,
                                        height=42, corner_radius=8,
                                        command=self.open_connect_dialog)
        self.btn_connect.pack(pady=10, padx=20, fill="x")
        
        self.btn_load = ctk.CTkButton(sidebar, text="📁 Ouvrir fichier MIDI",
                                     font=ctk.CTkFont(size=13),
                                     fg_color=Colors.BG_ELEVATED,
                                     text_color=Colors.TEXT_PRIMARY,
                                     height=40, corner_radius=8,
                                     command=self.load_midi_file)
        self.btn_load.pack(pady=5, padx=20, fill="x")
        
        # Séparateur
        ctk.CTkFrame(sidebar, height=1, fg_color=Colors.TEXT_MUTED).pack(pady=20, padx=25, fill="x")
        
        # Mode
        ctk.CTkLabel(sidebar, text="Mode de lecture",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color=Colors.TEXT_SECONDARY).pack(padx=20, anchor="w")
        
        ctk.CTkRadioButton(sidebar, text="Lecture continue",
                          variable=self.playback_mode, value="simple",
                          font=ctk.CTkFont(size=12),
                          fg_color=Colors.ACCENT_PRIMARY,
                          text_color=Colors.TEXT_PRIMARY).pack(padx=30, pady=8, anchor="w")
        
        ctk.CTkRadioButton(sidebar, text="Note par note",
                          variable=self.playback_mode, value="step",
                          font=ctk.CTkFont(size=12),
                          fg_color=Colors.ACCENT_PRIMARY,
                          text_color=Colors.TEXT_PRIMARY).pack(padx=30, anchor="w")
        
        self.loop_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sidebar, text="Répéter en boucle",
                       variable=self.loop_var,
                       font=ctk.CTkFont(size=12),
                       fg_color=Colors.ACCENT_PRIMARY,
                       text_color=Colors.TEXT_PRIMARY,
                       command=lambda: setattr(self, 'loop_playback', self.loop_var.get())
                       ).pack(padx=30, pady=15, anchor="w")
        
        # Légende
        legend = ctk.CTkFrame(sidebar, fg_color=Colors.BG_ELEVATED, corner_radius=10)
        legend.pack(pady=20, padx=20, fill="x", side="bottom")
        
        ctk.CTkLabel(legend, text="Légende", font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=Colors.TEXT_SECONDARY).pack(pady=(10, 5))
        
        for txt, col in [("● Main droite (≥Do4)", Colors.RIGHT_HAND),
                        ("● Main gauche (<Do4)", Colors.LEFT_HAND),
                        ("● Note en cours", Colors.NOTE_CURRENT)]:
            ctk.CTkLabel(legend, text=txt, font=ctk.CTkFont(size=10),
                        text_color=col).pack(anchor="w", padx=15)
        
        ctk.CTkLabel(legend, text="").pack(pady=3)

    def _setup_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=Colors.BG_DARK)
        main.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        
        # Header
        header = ctk.CTkFrame(main, fg_color="transparent", height=50)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        self.file_label = ctk.CTkLabel(header, text="Aucun fichier",
                                       font=ctk.CTkFont(size=18, weight="bold"),
                                       text_color=Colors.TEXT_PRIMARY)
        self.file_label.pack(side="left")
        
        self.info_label = ctk.CTkLabel(header, text="",
                                       font=ctk.CTkFont(size=12),
                                       text_color=Colors.TEXT_SECONDARY)
        self.info_label.pack(side="right")
        
        # Partition
        sheet_frame = ctk.CTkFrame(main, fg_color=Colors.BG_CARD, corner_radius=12)
        sheet_frame.grid(row=1, column=0, sticky="nsew")
        sheet_frame.grid_columnconfigure(0, weight=1)
        sheet_frame.grid_rowconfigure(0, weight=1)
        
        self.sheet_music = SheetMusicCanvas(sheet_frame)
        self.sheet_music.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        
        # Clavier
        kb_frame = ctk.CTkFrame(main, fg_color=Colors.BG_CARD, corner_radius=10, height=85)
        kb_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        kb_frame.grid_columnconfigure(0, weight=1)
        
        self.mini_keyboard = MiniKeyboard(kb_frame)
        self.mini_keyboard.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        
        # Contrôles
        ctrl_frame = ctk.CTkFrame(main, fg_color="transparent")
        ctrl_frame.grid(row=3, column=0, sticky="ew", pady=15)
        
        # Progression
        prog_frame = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(0, 10))
        
        self.time_label = ctk.CTkLabel(prog_frame, text="00:00",
                                       font=ctk.CTkFont(family="monospace", size=12),
                                       text_color=Colors.TEXT_SECONDARY)
        self.time_label.pack(side="left")
        
        self.progress = ctk.CTkProgressBar(prog_frame, progress_color=Colors.ACCENT_PRIMARY,
                                          fg_color=Colors.BG_ELEVATED, height=6)
        self.progress.pack(side="left", fill="x", expand=True, padx=15)
        self.progress.set(0)
        
        self.duration_label = ctk.CTkLabel(prog_frame, text="00:00",
                                          font=ctk.CTkFont(family="monospace", size=12),
                                          text_color=Colors.TEXT_SECONDARY)
        self.duration_label.pack(side="right")
        
        # Boutons lecture
        btn_frame = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        btn_frame.pack()
        
        ctk.CTkButton(btn_frame, text="⏮", width=50, height=50,
                     font=ctk.CTkFont(size=18),
                     fg_color=Colors.BG_ELEVATED,
                     corner_radius=25,
                     command=self.rewind).pack(side="left", padx=5)
        
        self.btn_play = ctk.CTkButton(btn_frame, text="▶", width=65, height=65,
                                     font=ctk.CTkFont(size=26),
                                     fg_color=Colors.ACCENT_PRIMARY,
                                     corner_radius=32,
                                     command=self.toggle_play)
        self.btn_play.pack(side="left", padx=10)
        
        ctk.CTkButton(btn_frame, text="⏹", width=50, height=50,
                     font=ctk.CTkFont(size=18),
                     fg_color=Colors.BG_ELEVATED,
                     corner_radius=25,
                     command=self.stop).pack(side="left", padx=5)
        
        # Logs
        self.log_box = ctk.CTkTextbox(main, height=60,
                                     font=ctk.CTkFont(family="monospace", size=10),
                                     fg_color=Colors.BG_CARD,
                                     text_color=Colors.TEXT_SECONDARY,
                                     corner_radius=8)
        self.log_box.grid(row=4, column=0, sticky="ew", pady=(10, 0))

    # --- Lecture ---
    def _play_thread(self):
        try:
            mid = mido.MidiFile(self.current_midi_file)
            duration = mid.length
            
            while True:
                current_time = 0.0
                mode = self.playback_mode.get()
                
                self.after(0, lambda: self._update_ui(0, duration))
                
                if mode == "simple":
                    for msg in mid.play(meta_messages=True):
                        if self.stop_event.is_set():
                            return
                        while self.is_paused:
                            if self.stop_event.is_set():
                                return
                            if self.rewind_event.is_set():
                                break
                            time.sleep(0.05)
                        if self.rewind_event.is_set():
                            break
                        
                        current_time += msg.time
                        
                        if not msg.is_meta:
                            asyncio.run_coroutine_threadsafe(
                                self.bt_manager.send_midi(msg.bytes()), self.loop)
                            
                            if msg.type == 'note_on' and msg.velocity > 0:
                                self.after(0, lambda n=msg.note: self.mini_keyboard.add_note(n))
                            else:
                                self.after(0, lambda n=msg.note: self.mini_keyboard.remove_note(n))
                        
                        self.after(0, lambda t=current_time, d=duration: self._update_ui(t, d))
                else:
                    # Note par note
                    msgs = list(mido.merge_tracks(mid.tracks))
                    for msg in msgs:
                        if self.stop_event.is_set():
                            return
                        if self.rewind_event.is_set():
                            break
                        while self.is_paused:
                            if self.stop_event.is_set():
                                return
                            if self.rewind_event.is_set():
                                break
                            time.sleep(0.05)
                        if self.rewind_event.is_set():
                            break
                        
                        current_time += msg.time
                        
                        if msg.type == 'note_on' and msg.velocity > 0:
                            asyncio.run_coroutine_threadsafe(
                                self.bt_manager.send_midi(msg.bytes()), self.loop)
                            
                            self.after(0, lambda n=msg.note: self.mini_keyboard.add_note(n))
                            self.log(f"🎹 Jouez: {get_note_name(msg.note)}")
                            self.after(0, lambda t=current_time, d=duration: self._update_ui(t, d))
                            
                            self.next_note_event.clear()
                            while not self.next_note_event.is_set():
                                if self.stop_event.is_set() or self.rewind_event.is_set():
                                    break
                                time.sleep(0.03)
                            
                            self.after(0, lambda n=msg.note: self.mini_keyboard.remove_note(n))
                        
                        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                            asyncio.run_coroutine_threadsafe(
                                self.bt_manager.send_midi(msg.bytes()), self.loop)
                
                if self.rewind_event.is_set():
                    self.log("⏪ Retour au début")
                    self.rewind_event.clear()
                    asyncio.run_coroutine_threadsafe(self.bt_manager.send_reset(), self.loop)
                    self.after(0, lambda: self.mini_keyboard.set_active([]))
                    continue
                
                if self.stop_event.is_set() or not self.loop_playback:
                    break
                
                self.log("🔄 Répétition...")
                time.sleep(0.5)
                
        except Exception as e:
            self.log(f"❌ Erreur: {e}")
        finally:
            self.is_playing = False
            self.after(0, lambda: self.btn_play.configure(text="▶"))
            self.after(0, lambda: self.mini_keyboard.set_active([]))
            self.log("⏹ Terminé")

    def _update_ui(self, t, duration):
        try:
            if duration > 0:
                self.progress.set(t / duration)
            self.time_label.configure(text=f"{int(t)//60:02}:{int(t)%60:02}")
            self.sheet_music.update_time(t)
        except:
            pass

    # --- Événements ---
    def on_piano_input(self, note):
        if self.is_playing and self.playback_mode.get() == "step":
            self.next_note_event.set()
            self.log(f"✓ {get_note_name(note)}")

    def log(self, msg):
        self.log_box.insert("end", f"{msg}\n")
        self.log_box.see("end")

    def _on_connect_ok(self, _):
        self.status_dot.configure(text_color=Colors.ACCENT_SUCCESS)
        self.status_label.configure(text="Connecté")
        self.device_label.configure(text=self.bt_manager.device_name or "Piano")
        self.btn_connect.configure(text="Déconnecter", fg_color=Colors.BG_ELEVATED)
        self.log(f"✅ Connecté: {self.bt_manager.device_name}")

    def _on_connect_fail(self, err):
        self.status_dot.configure(text_color="#EF4444")
        self.status_label.configure(text="Déconnecté")
        self.device_label.configure(text="Aucun appareil")
        self.btn_connect.configure(text="Connecter Piano", fg_color=Colors.ACCENT_PRIMARY)
        self.log(f"❌ Erreur: {err}")

    def open_connect_dialog(self):
        if self.bt_manager.is_connected:
            self.run_async(self.bt_manager.disconnect(),
                          lambda _: self._on_connect_fail(None))
            self.log("🔌 Déconnexion")
            return
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Appareils Bluetooth")
        dialog.geometry("400x350")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=Colors.BG_DARK)
        
        ctk.CTkLabel(dialog, text="🔍 Recherche...",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=Colors.TEXT_PRIMARY).pack(pady=15)
        
        scroll = ctk.CTkScrollableFrame(dialog, fg_color=Colors.BG_CARD, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=15, pady=10)
        
        async def scan():
            devices = await BleakScanner.discover()
            for dev in devices:
                name = dev.name or "Inconnu"
                ctk.CTkButton(
                    scroll, text=f"🎹 {name}\n{dev.address}",
                    font=ctk.CTkFont(size=12),
                    fg_color=Colors.BG_ELEVATED,
                    text_color=Colors.TEXT_PRIMARY,
                    height=55, corner_radius=8, anchor="w",
                    command=lambda d=dev: [
                        dialog.destroy(),
                        self.run_async(self.bt_manager.connect(d),
                                      self._on_connect_ok, self._on_connect_fail)
                    ]
                ).pack(fill="x", pady=4, padx=8)
        
        self.run_async(scan())

    def load_midi_file(self):
        path = filedialog.askopenfilename(
            title="Ouvrir fichier MIDI",
            filetypes=[("MIDI", "*.mid *.midi")]
        )
        if path:
            self.current_midi_file = path
            name = os.path.basename(path)
            self.file_label.configure(text=name)
            
            self.sheet_music.load_midi(path)
            
            dur = self.sheet_music.midi_duration
            self.duration_label.configure(text=f"{int(dur)//60:02}:{int(dur)%60:02}")
            self.info_label.configure(text=f"{len(self.sheet_music.events)} notes")
            
            self.log(f"📂 {name}")
            self.stop()
            self.run_async(self.bt_manager.send_reset())

    def toggle_play(self):
        if not self.current_midi_file:
            self.log("⚠️ Chargez un fichier MIDI")
            return
        
        if self.is_playing:
            self.is_paused = not self.is_paused
            self.btn_play.configure(text="▶" if self.is_paused else "⏸")
            self.log("⏸ Pause" if self.is_paused else "▶ Reprise")
        else:
            self.is_playing = True
            self.is_paused = False
            self.stop_event.clear()
            self.rewind_event.clear()
            self.btn_play.configure(text="⏸")
            threading.Thread(target=self._play_thread, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.is_playing = False
        self.is_paused = False
        self.btn_play.configure(text="▶")
        self.progress.set(0)
        self.time_label.configure(text="00:00")
        self.sheet_music.update_time(0)
        self.mini_keyboard.set_active([])

    def rewind(self):
        if self.is_playing:
            self.rewind_event.set()
        else:
            self.progress.set(0)
            self.time_label.configure(text="00:00")
            self.sheet_music.update_time(0)
            self.run_async(self.bt_manager.send_reset())


if __name__ == "__main__":
    app = PianoApp()
    app.mainloop()