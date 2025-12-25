"""
Piano Bluetooth Master v3.1
"""
import asyncio, threading, os, json, time
from tkinter import filedialog
import customtkinter as ctk
from bleak import BleakClient, BleakScanner
import mido

ctk.set_appearance_mode("Dark")
CONFIG_FILE = "piano_config.json"

class Colors:
    BG_DARK, BG_CARD, BG_ELEVATED = "#0D1117", "#161B22", "#21262D"
    STAFF_LINE, STAFF_BG = "#4A5568", "#1A1F2A"
    NOTE_PAST, NOTE_CURRENT = "#3D4450", "#FBBF24"
    ACCENT_PRIMARY, ACCENT_SUCCESS = "#8B5CF6", "#10B981"
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED = "#F0F6FC", "#8B949E", "#484F58"
    RIGHT_HAND, LEFT_HAND, PLAYHEAD = "#10B981", "#F59E0B", "#EF4444"

NOTE_NAMES = ['Do','Do#','Ré','Ré#','Mi','Fa','Fa#','Sol','Sol#','La','La#','Si']
def get_note_name(n): return f"{NOTE_NAMES[n%12]}{n//12-1}"
def is_sharp(n): return (n%12) in [1,3,6,8,10]

def note_to_pos(midi_note):
    note_pos = [0,0,1,1,2,3,3,4,4,5,5,6]
    abs_pos = (midi_note//12)*7 + note_pos[midi_note%12]
    if midi_note >= 60: return (41 - abs_pos, "treble")
    return (29 - abs_pos, "bass")

class MidiEvent:
    def __init__(self, time, note, vel, dur=0.5):
        self.time, self.note, self.velocity, self.duration = time, note, vel, dur
    @property
    def name(self): return get_note_name(self.note)
    @property
    def is_right_hand(self): return self.note >= 60

class BluetoothManager:
    def __init__(self, loop, cb=None):
        self.client, self.loop, self.input_callback = None, loop, cb
        self.device_address = self.device_name = self.midi_uuid = None
        self.is_connected, self.write_type = False, "write-without-response"
        self.load_config()
    
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    c = json.load(f)
                    self.device_address, self.device_name, self.midi_uuid = c.get('device_address'), c.get('device_name'), c.get('midi_uuid')
            except: pass
    
    def save_config(self):
        try:
            with open(CONFIG_FILE,'w') as f: json.dump({'device_address':self.device_address,'device_name':self.device_name,'midi_uuid':self.midi_uuid}, f)
        except: pass

    async def connect(self, device=None):
        target = device or self.device_address
        if not target: raise Exception("Aucun appareil")
        if device: self.device_address, self.device_name = device.address, device.name
        self.client = BleakClient(target)
        await self.client.connect()
        await asyncio.sleep(1.0)
        await self._setup()
        self.is_connected = True
        self.save_config()
        return True

    async def _setup(self):
        wc = nc = None
        if not self.client.services: await self.client.get_services()
        for s in self.client.services:
            for c in s.characteristics:
                if "write-without-response" in c.properties: wc, self.write_type = c, "write-without-response"
                elif "write" in c.properties and not wc: wc, self.write_type = c, "write"
                if "notify" in c.properties: nc = c
        if not wc: raise Exception("Pas de MIDI")
        self.midi_uuid = wc.uuid
        if nc:
            try: await self.client.start_notify(nc.uuid, self._notif)
            except: pass

    def _notif(self, s, d):
        if len(d)>=3:
            for i in range(len(d)-2):
                if 0x90<=d[i]<=0x9F and d[i+2]>0 and self.input_callback:
                    self.loop.call_soon_threadsafe(self.input_callback, d[i+1])

    async def send_midi(self, data):
        if self.is_connected and self.client:
            try: await self.client.write_gatt_char(self.midi_uuid, bytearray([0x80,0x80]+list(data)), response=self.write_type=="write")
            except: pass

    async def send_reset(self):
        if self.is_connected:
            for ch in range(16): await self.send_midi([0xB0|ch,123,0])

    async def disconnect(self):
        if self.client:
            try: await self.client.disconnect()
            except: pass
        self.is_connected = False

class SheetMusicCanvas(ctk.CTkCanvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=Colors.STAFF_BG, highlightthickness=0, **kw)
        self.ls, self.pps, self.nrx, self.nry = 12, 120, 6, 5
        self.ml, self.phx = 70, 180
        self.ty, self.by = 100, 220
        self.events, self.ct, self.md = [], 0.0, 0.0
        self.bind("<Configure>", self._resize)
    
    def _resize(self, e):
        if e.height > 100:
            self.ty, self.by = int(e.height*0.28), int(e.height*0.68)
            self.redraw()
    
    def load_midi(self, fp):
        self.events = []
        try:
            mid = mido.MidiFile(fp)
            active, t = {}, 0.0
            for m in mido.merge_tracks(mid.tracks):
                t += m.time
                if m.type=='note_on' and m.velocity>0: active[(m.channel,m.note)]=(t,m.velocity)
                elif m.type=='note_off' or (m.type=='note_on' and m.velocity==0):
                    k = (m.channel,m.note)
                    if k in active:
                        st,v = active.pop(k)
                        self.events.append(MidiEvent(st, m.note, v, max(0.1,t-st)))
            self.events.sort(key=lambda e:e.time)
            self.md, self.ct = t, 0
            self.redraw()
        except Exception as e: print(f"Err: {e}")
    
    def t2x(self, t): return self.phx + (t-self.ct)*self.pps
    
    def n2y(self, n):
        p, c = note_to_pos(n)
        return (self.ty if c=="treble" else self.by) + p*(self.ls/2), c
    
    def draw_staves(self):
        w = max(self.winfo_width(), 800)
        for i in range(-2,3):
            self.create_line(self.ml-10, self.ty+i*self.ls, w, self.ty+i*self.ls, fill=Colors.STAFF_LINE)
            self.create_line(self.ml-10, self.by+i*self.ls, w, self.by+i*self.ls, fill=Colors.STAFF_LINE)
        top, bot = self.ty-2*self.ls, self.by+2*self.ls
        self.create_line(self.ml-10, top, self.ml-10, bot, fill=Colors.TEXT_PRIMARY, width=2)
        self.create_text(self.ml-35, self.ty+5, text="𝄞", font=("Times",38), fill=Colors.TEXT_PRIMARY)
        self.create_text(self.ml-35, self.by-3, text="𝄢", font=("Times",34), fill=Colors.TEXT_PRIMARY)
    
    def draw_ledger(self, x, y, clef):
        top = (self.ty if clef=="treble" else self.by) - 2*self.ls
        bot = (self.ty if clef=="treble" else self.by) + 2*self.ls
        hw = self.nrx + 6
        if y < top-3:
            ly = top - self.ls
            while ly >= y-3: self.create_line(x-hw,ly,x+hw,ly,fill=Colors.STAFF_LINE); ly -= self.ls
        if y > bot+3:
            ly = bot + self.ls
            while ly <= y+3: self.create_line(x-hw,ly,x+hw,ly,fill=Colors.STAFF_LINE); ly += self.ls
        c4y,_ = self.n2y(60)
        if abs(y-c4y)<3:
            mid = (self.ty+self.by)/2
            self.create_line(x-hw,mid,x+hw,mid,fill=Colors.STAFF_LINE)
    
    def draw_note(self, ev, st):
        x, (y, clef) = self.t2x(ev.time), self.n2y(ev.note)
        col = Colors.NOTE_PAST if st=="past" else Colors.NOTE_CURRENT if st=="current" else (Colors.RIGHT_HAND if ev.is_right_hand else Colors.LEFT_HAND)
        self.draw_ledger(x, y, clef)
        if is_sharp(ev.note): self.create_text(x-self.nrx-10, y, text="♯", font=("Arial",11), fill=col)
        rx, ry = self.nrx, self.nry
        if ev.duration >= 2.0: self.create_oval(x-rx,y-ry,x+rx,y+ry,outline=col,width=2)
        elif ev.duration >= 1.0:
            self.create_oval(x-rx,y-ry,x+rx,y+ry,outline=col,width=2)
            self._stem(x,y,clef,col)
        else:
            self.create_oval(x-rx,y-ry,x+rx,y+ry,fill=col,outline=col)
            self._stem(x,y,clef,col)
        if st=="current":
            self.create_oval(x-rx-6,y-ry-6,x+rx+6,y+ry+6,outline=Colors.NOTE_CURRENT,width=2)
            self.create_text(x,y-ry-14,text=ev.name,font=("Arial",9,"bold"),fill=Colors.NOTE_CURRENT)
    
    def _stem(self, x, y, clef, col):
        ref = self.ty if clef=="treble" else self.by
        up = y > ref
        sx = x + self.nrx - 1 if up else x - self.nrx + 1
        sy = y - 32 if up else y + 32
        self.create_line(sx,y,sx,sy,fill=col,width=1.5)
    
    def draw_playhead(self):
        top, bot = self.ty-3*self.ls, self.by+3*self.ls
        self.create_line(self.phx,top,self.phx,bot,fill=Colors.PLAYHEAD,width=2)
        self.create_polygon(self.phx-7,top-10,self.phx+7,top-10,self.phx,top-2,fill=Colors.PLAYHEAD)
    
    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w<50 or h<50: return
        self.create_rectangle(0,0,w,h,fill=Colors.STAFF_BG,outline="")
        self.draw_staves()
        tl = self.ct - self.phx/self.pps
        tr = self.ct + (w-self.phx)/self.pps
        for ev in self.events:
            if ev.time < tl-0.5 or ev.time > tr+0.5: continue
            d = ev.time - self.ct
            st = "past" if d<-0.1 else "current" if d<0.25 else "future"
            self.draw_note(ev, st)
        self.draw_playhead()
    
    def update_time(self, t): self.ct = t; self.redraw()

class MiniKeyboard(ctk.CTkCanvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=Colors.BG_CARD, highlightthickness=0, height=65, **kw)
        self.active, self.sn, self.en = set(), 36, 96
        self.bind("<Configure>", lambda e: self.redraw())
    
    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50: return
        wn = [n for n in range(self.sn, self.en+1) if not is_sharp(n)]
        kw, wh, bh = w/len(wn), h-4, (h-4)*0.6
        wx, x = {}, 0
        for n in range(self.sn, self.en+1):
            if not is_sharp(n):
                c = Colors.ACCENT_SUCCESS if n in self.active else "#EAEAEA"
                self.create_rectangle(x,2,x+kw-1,wh,fill=c,outline="#999")
                wx[n] = x
                if n==60: self.create_oval(x+kw/2-3,wh-10,x+kw/2+3,wh-4,fill=Colors.ACCENT_PRIMARY)
                x += kw
        for n in range(self.sn, self.en+1):
            if is_sharp(n) and n-1 in wx:
                bx = wx[n-1] + kw*0.7
                c = Colors.LEFT_HAND if n in self.active else "#1A1A2E"
                self.create_rectangle(bx,2,bx+kw*0.6,bh,fill=c,outline="#333")
    
    def set_active(self, n): self.active = set(n); self.redraw()
    def add_note(self, n): self.active.add(n); self.redraw()
    def remove_note(self, n): self.active.discard(n); self.redraw()

class PianoApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=lambda: (asyncio.set_event_loop(self.loop), self.loop.run_forever()), daemon=True).start()
        self.bt = BluetoothManager(self.loop, cb=self.on_input)
        self.midi_file = None
        self.playing = self.paused = False
        self.stop_ev, self.rew_ev, self.next_ev = threading.Event(), threading.Event(), threading.Event()
        self.loop_pb = False
        self.mode = ctk.StringVar(value="simple")
        self.title("🎹 Piano Master")
        self.geometry("1300x750")
        self.configure(fg_color=Colors.BG_DARK)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._sidebar()
        self._main()
        if self.bt.device_address:
            self.log("🔄 Reconnexion...")
            self._async(self.bt.connect(), self._conn_ok, self._conn_fail)

    def _async(self, coro, ok=None, err=None):
        def w():
            f = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                r = f.result()
                if ok: self.after(0, ok, r)
            except Exception as e:
                if err: self.after(0, err, e)
        threading.Thread(target=w, daemon=True).start()

    def _sidebar(self):
        sb = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color=Colors.BG_CARD)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="🎹 Piano Master", font=ctk.CTkFont(size=18,weight="bold"), text_color=Colors.TEXT_PRIMARY).pack(pady=(20,2))
        sf = ctk.CTkFrame(sb, fg_color=Colors.BG_ELEVATED, corner_radius=8)
        sf.pack(pady=15, padx=15, fill="x")
        r = ctk.CTkFrame(sf, fg_color="transparent")
        r.pack(pady=8, padx=10, fill="x")
        self.dot = ctk.CTkLabel(r, text="●", text_color="#EF4444", font=("Arial",12))
        self.dot.pack(side="left")
        self.slbl = ctk.CTkLabel(r, text="Déconnecté", font=ctk.CTkFont(size=11), text_color=Colors.TEXT_SECONDARY)
        self.slbl.pack(side="left", padx=5)
        self.dlbl = ctk.CTkLabel(sf, text="", font=ctk.CTkFont(size=9), text_color=Colors.TEXT_MUTED)
        self.dlbl.pack(pady=(0,6))
        self.bcn = ctk.CTkButton(sb, text="Connecter", font=ctk.CTkFont(size=12,weight="bold"), fg_color=Colors.ACCENT_PRIMARY, height=36, command=self.connect_dlg)
        self.bcn.pack(pady=6, padx=15, fill="x")
        ctk.CTkButton(sb, text="📁 Ouvrir MIDI", font=ctk.CTkFont(size=11), fg_color=Colors.BG_ELEVATED, text_color=Colors.TEXT_PRIMARY, height=34, command=self.load_midi).pack(pady=4, padx=15, fill="x")
        ctk.CTkFrame(sb, height=1, fg_color=Colors.TEXT_MUTED).pack(pady=12, padx=18, fill="x")
        ctk.CTkLabel(sb, text="Mode", font=ctk.CTkFont(size=10,weight="bold"), text_color=Colors.TEXT_SECONDARY).pack(padx=15, anchor="w")
        ctk.CTkRadioButton(sb, text="Continue", variable=self.mode, value="simple", font=ctk.CTkFont(size=10), fg_color=Colors.ACCENT_PRIMARY, text_color=Colors.TEXT_PRIMARY).pack(padx=25, pady=4, anchor="w")
        ctk.CTkRadioButton(sb, text="Note/note", variable=self.mode, value="step", font=ctk.CTkFont(size=10), fg_color=Colors.ACCENT_PRIMARY, text_color=Colors.TEXT_PRIMARY).pack(padx=25, anchor="w")
        self.lpv = ctk.BooleanVar()
        ctk.CTkCheckBox(sb, text="Boucle", variable=self.lpv, font=ctk.CTkFont(size=10), fg_color=Colors.ACCENT_PRIMARY, text_color=Colors.TEXT_PRIMARY, command=lambda: setattr(self,'loop_pb',self.lpv.get())).pack(padx=25, pady=8, anchor="w")
        lg = ctk.CTkFrame(sb, fg_color=Colors.BG_ELEVATED, corner_radius=8)
        lg.pack(pady=10, padx=15, fill="x", side="bottom")
        for t,c in [("● Droite",Colors.RIGHT_HAND),("● Gauche",Colors.LEFT_HAND),("● Active",Colors.NOTE_CURRENT)]:
            ctk.CTkLabel(lg, text=t, font=ctk.CTkFont(size=9), text_color=c).pack(anchor="w", padx=10)
        ctk.CTkLabel(lg, text="").pack(pady=2)

    def _main(self):
        m = ctk.CTkFrame(self, corner_radius=0, fg_color=Colors.BG_DARK)
        m.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        m.grid_columnconfigure(0, weight=1)
        m.grid_rowconfigure(1, weight=1)
        h = ctk.CTkFrame(m, fg_color="transparent", height=30)
        h.grid(row=0, column=0, sticky="ew", pady=(0,6))
        self.flbl = ctk.CTkLabel(h, text="Aucun fichier", font=ctk.CTkFont(size=14,weight="bold"), text_color=Colors.TEXT_PRIMARY)
        self.flbl.pack(side="left")
        self.ilbl = ctk.CTkLabel(h, text="", font=ctk.CTkFont(size=10), text_color=Colors.TEXT_SECONDARY)
        self.ilbl.pack(side="right")
        sf = ctk.CTkFrame(m, fg_color=Colors.BG_CARD, corner_radius=8)
        sf.grid(row=1, column=0, sticky="nsew")
        sf.grid_columnconfigure(0, weight=1)
        sf.grid_rowconfigure(0, weight=1)
        self.sheet = SheetMusicCanvas(sf)
        self.sheet.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        kf = ctk.CTkFrame(m, fg_color=Colors.BG_CARD, corner_radius=6, height=70)
        kf.grid(row=2, column=0, sticky="ew", pady=(6,0))
        kf.grid_columnconfigure(0, weight=1)
        self.kb = MiniKeyboard(kf)
        self.kb.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        cf = ctk.CTkFrame(m, fg_color="transparent")
        cf.grid(row=3, column=0, sticky="ew", pady=10)
        pf = ctk.CTkFrame(cf, fg_color="transparent")
        pf.pack(fill="x", pady=(0,6))
        self.tlbl = ctk.CTkLabel(pf, text="00:00", font=ctk.CTkFont(family="monospace",size=10), text_color=Colors.TEXT_SECONDARY)
        self.tlbl.pack(side="left")
        self.prog = ctk.CTkProgressBar(pf, progress_color=Colors.ACCENT_PRIMARY, fg_color=Colors.BG_ELEVATED, height=4)
        self.prog.pack(side="left", fill="x", expand=True, padx=10)
        self.prog.set(0)
        self.durlbl = ctk.CTkLabel(pf, text="00:00", font=ctk.CTkFont(family="monospace",size=10), text_color=Colors.TEXT_SECONDARY)
        self.durlbl.pack(side="right")
        bf = ctk.CTkFrame(cf, fg_color="transparent")
        bf.pack()
        ctk.CTkButton(bf, text="⏮", width=40, height=40, font=ctk.CTkFont(size=14), fg_color=Colors.BG_ELEVATED, corner_radius=20, command=self.rewind).pack(side="left", padx=3)
        self.bpl = ctk.CTkButton(bf, text="▶", width=55, height=55, font=ctk.CTkFont(size=22), fg_color=Colors.ACCENT_PRIMARY, corner_radius=27, command=self.toggle_play)
        self.bpl.pack(side="left", padx=6)
        ctk.CTkButton(bf, text="⏹", width=40, height=40, font=ctk.CTkFont(size=14), fg_color=Colors.BG_ELEVATED, corner_radius=20, command=self.stop).pack(side="left", padx=3)
        self.logb = ctk.CTkTextbox(m, height=50, font=ctk.CTkFont(family="monospace",size=9), fg_color=Colors.BG_CARD, text_color=Colors.TEXT_SECONDARY, corner_radius=5)
        self.logb.grid(row=4, column=0, sticky="ew", pady=(6,0))

    def _play(self):
        try:
            mid = mido.MidiFile(self.midi_file)
            dur = mid.length
            while True:
                ct = 0.0
                self.after(0, lambda: self._ui(0, dur))
                if self.mode.get() == "simple":
                    for msg in mid.play(meta_messages=True):
                        if self.stop_ev.is_set(): return
                        while self.paused:
                            if self.stop_ev.is_set(): return
                            if self.rew_ev.is_set(): break
                            time.sleep(0.05)
                        if self.rew_ev.is_set(): break
                        ct += msg.time
                        if hasattr(msg,'bytes'):
                            try: asyncio.run_coroutine_threadsafe(self.bt.send_midi(msg.bytes()), self.loop)
                            except: pass
                        if msg.type=='note_on' and hasattr(msg,'note'):
                            if msg.velocity>0: self.after(0, lambda n=msg.note: self.kb.add_note(n))
                            else: self.after(0, lambda n=msg.note: self.kb.remove_note(n))
                        elif msg.type=='note_off' and hasattr(msg,'note'):
                            self.after(0, lambda n=msg.note: self.kb.remove_note(n))
                        self.after(0, lambda t=ct,d=dur: self._ui(t,d))
                else:
                    for msg in mido.merge_tracks(mid.tracks):
                        if self.stop_ev.is_set(): return
                        if self.rew_ev.is_set(): break
                        while self.paused:
                            if self.stop_ev.is_set(): return
                            if self.rew_ev.is_set(): break
                            time.sleep(0.05)
                        if self.rew_ev.is_set(): break
                        ct += msg.time
                        if msg.type=='note_on' and hasattr(msg,'note') and msg.velocity>0:
                            if hasattr(msg,'bytes'): asyncio.run_coroutine_threadsafe(self.bt.send_midi(msg.bytes()), self.loop)
                            self.after(0, lambda n=msg.note: self.kb.add_note(n))
                            self.log(f"🎹 {get_note_name(msg.note)}")
                            self.after(0, lambda t=ct,d=dur: self._ui(t,d))
                            self.next_ev.clear()
                            while not self.next_ev.is_set():
                                if self.stop_ev.is_set() or self.rew_ev.is_set(): break
                                time.sleep(0.03)
                            self.after(0, lambda n=msg.note: self.kb.remove_note(n))
                        elif (msg.type=='note_off' or (msg.type=='note_on' and hasattr(msg,'velocity') and msg.velocity==0)) and hasattr(msg,'note'):
                            if hasattr(msg,'bytes'): asyncio.run_coroutine_threadsafe(self.bt.send_midi(msg.bytes()), self.loop)
                            self.after(0, lambda n=msg.note: self.kb.remove_note(n))
                if self.rew_ev.is_set():
                    self.log("⏪")
                    self.rew_ev.clear()
                    asyncio.run_coroutine_threadsafe(self.bt.send_reset(), self.loop)
                    self.after(0, lambda: self.kb.set_active([]))
                    continue
                if self.stop_ev.is_set() or not self.loop_pb: break
                self.log("🔄")
                time.sleep(0.5)
        except Exception as e: self.log(f"❌ {e}")
        finally:
            self.playing = False
            self.after(0, lambda: self.bpl.configure(text="▶"))
            self.after(0, lambda: self.kb.set_active([]))
            self.log("⏹")

    def _ui(self, t, d):
        if d>0: self.prog.set(t/d)
        self.tlbl.configure(text=f"{int(t)//60:02}:{int(t)%60:02}")
        self.sheet.update_time(t)

    def on_input(self, n):
        if self.playing and self.mode.get()=="step":
            self.next_ev.set()
            self.log(f"✓ {get_note_name(n)}")

    def log(self, m): self.logb.insert("end", f"{m}\n"); self.logb.see("end")
    def _conn_ok(self, _):
        self.dot.configure(text_color=Colors.ACCENT_SUCCESS)
        self.slbl.configure(text="Connecté")
        self.dlbl.configure(text=self.bt.device_name or "")
        self.bcn.configure(text="Déconnecter", fg_color=Colors.BG_ELEVATED)
        self.log(f"✅ {self.bt.device_name}")
    def _conn_fail(self, e):
        self.dot.configure(text_color="#EF4444")
        self.slbl.configure(text="Déconnecté")
        self.dlbl.configure(text="")
        self.bcn.configure(text="Connecter", fg_color=Colors.ACCENT_PRIMARY)
        if e: self.log(f"❌ {e}")

    def connect_dlg(self):
        if self.bt.is_connected:
            self._async(self.bt.disconnect(), lambda _: self._conn_fail(None))
            return
        d = ctk.CTkToplevel(self)
        d.title("Bluetooth")
        d.geometry("350x300")
        d.transient(self)
        d.grab_set()
        d.configure(fg_color=Colors.BG_DARK)
        ctk.CTkLabel(d, text="🔍 Recherche...", font=ctk.CTkFont(size=12,weight="bold"), text_color=Colors.TEXT_PRIMARY).pack(pady=10)
        s = ctk.CTkScrollableFrame(d, fg_color=Colors.BG_CARD, corner_radius=6)
        s.pack(fill="both", expand=True, padx=10, pady=8)
        async def scan():
            devs = await BleakScanner.discover()
            for dv in devs:
                nm = dv.name or "?"
                ctk.CTkButton(s, text=f"🎹 {nm}\n{dv.address}", font=ctk.CTkFont(size=10), fg_color=Colors.BG_ELEVATED, text_color=Colors.TEXT_PRIMARY, height=45, corner_radius=5, anchor="w", command=lambda x=dv: [d.destroy(), self._async(self.bt.connect(x), self._conn_ok, self._conn_fail)]).pack(fill="x", pady=2, padx=4)
        self._async(scan())

    def load_midi(self):
        p = filedialog.askopenfilename(filetypes=[("MIDI","*.mid *.midi")])
        if p:
            self.midi_file = p
            self.flbl.configure(text=os.path.basename(p))
            self.sheet.load_midi(p)
            self.durlbl.configure(text=f"{int(self.sheet.md)//60:02}:{int(self.sheet.md)%60:02}")
            self.ilbl.configure(text=f"{len(self.sheet.events)} notes")
            self.log(f"📂 {os.path.basename(p)}")
            self.stop()
            self._async(self.bt.send_reset())

    def toggle_play(self):
        if not self.midi_file: self.log("⚠️ Charger MIDI"); return
        if self.playing:
            self.paused = not self.paused
            self.bpl.configure(text="▶" if self.paused else "⏸")
        else:
            self.playing, self.paused = True, False
            self.stop_ev.clear()
            self.rew_ev.clear()
            self.bpl.configure(text="⏸")
            threading.Thread(target=self._play, daemon=True).start()

    def stop(self):
        self.stop_ev.set()
        self.playing = self.paused = False
        self.bpl.configure(text="▶")
        self.prog.set(0)
        self.tlbl.configure(text="00:00")
        self.sheet.update_time(0)
        self.kb.set_active([])

    def rewind(self):
        if self.playing: self.rew_ev.set()
        else: self.prog.set(0); self.tlbl.configure(text="00:00"); self.sheet.update_time(0); self._async(self.bt.send_reset())

if __name__ == "__main__":
    PianoApp().mainloop()