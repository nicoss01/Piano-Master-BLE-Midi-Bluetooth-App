import asyncio
import os
import sys
import json
from bleak import BleakClient, BleakScanner
import mido
from aioconsole import ainput

# --- CONFIGURATION ---
CONFIG_FILE = "piano_config.json"
MIDI_FOLDER = "midi_files"

class PianoController:
    def __init__(self):
        self.client = None
        self.is_connected = False
        self.is_paused = False
        self.stop_requested = False
        self.rewind_requested = False
        
        # Paramètres chargés depuis la config ou découverts
        self.device_address = None
        self.device_name = None
        self.midi_uuid = None
        
        self.load_config()

    def load_config(self):
        """Charge la configuration depuis le fichier JSON."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.device_address = config.get('device_address')
                    self.device_name = config.get('device_name')
                    self.midi_uuid = config.get('midi_uuid')
                    print(f"⚙️  Configuration chargée pour : {self.device_name}")
            except Exception as e:
                print(f"⚠️ Erreur de chargement config: {e}")

    def save_config(self):
        """Sauvegarde la configuration actuelle."""
        config = {
            'device_address': self.device_address,
            'device_name': self.device_name,
            'midi_uuid': self.midi_uuid
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
            print("💾 Configuration sauvegardée pour la prochaine fois.")
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde config: {e}")

    async def select_device(self):
        """Scanne et demande à l'utilisateur de choisir un appareil."""
        print("\n🔍 Scan des appareils Bluetooth en cours...")
        devices = await BleakScanner.discover()
        
        candidates = []
        for d in devices:
            name = d.name or "Inconnu"
            # On garde tout, mais on met en évidence ceux qui ressemblent à des pianos
            candidates.append(d)

        if not candidates:
            print("❌ Aucun appareil Bluetooth trouvé.")
            return None

        print("\n--- APPAREILS TROUVÉS ---")
        recommended_indices = []
        
        for i, d in enumerate(candidates):
            name = d.name or "Inconnu"
            marker = ""
            # Marquer les appareils probables
            if any(x in name.lower() for x in ["piano", "midi", "key", "ble", "roland", "yamaha", "kawai"]):
                marker = "🎹 (Recommandé)"
                recommended_indices.append(i)
            print(f"[{i+1}] {name} ({d.address}) {marker}")

        while True:
            choice = await ainput("\nChoisissez le numéro de votre piano (ou 'r' pour re-scanner) : ")
            if choice.lower() == 'r':
                return await self.select_device() # Récursion pour re-scanner
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx]
            except ValueError:
                pass
            print("❌ Choix invalide.")

    async def select_characteristic(self):
        """Liste les caractéristiques d'écriture disponibles et demande choix."""
        print("\n🕵️  Analyse des services du piano...")
        writable_chars = []

        for service in self.client.services:
            for char in service.characteristics:
                props = char.properties
                # On cherche les caractéristiques où on peut écrire
                if "write" in props or "write-without-response" in props:
                    writable_chars.append({
                        "uuid": char.uuid,
                        "desc": char.description,
                        "props": props
                    })

        if not writable_chars:
            print("❌ Aucune caractéristique d'écriture trouvée sur cet appareil !")
            return None

        # Si une seule caractéristique trouvée, on la prend auto
        if len(writable_chars) == 1:
            c = writable_chars[0]
            print(f"✅ Une seule caractéristique d'écriture trouvée, sélection automatique : {c['uuid']}")
            return c['uuid']

        print("\n--- CANAUX DE COMMUNICATION (UUID) ---")
        print("Il faut choisir où envoyer les notes. Cherchez 'MIDI' ou essayez le premier.")
        for i, c in enumerate(writable_chars):
            print(f"[{i+1}] UUID: {c['uuid']}")
            print(f"    Desc: {c['desc']} | Props: {c['props']}")

        while True:
            choice = await ainput("\nChoisissez le numéro de l'UUID : ")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(writable_chars):
                    return writable_chars[idx]['uuid']
            except ValueError:
                pass
            print("❌ Choix invalide.")

    async def setup(self):
        """Gère tout le processus de connexion (Auto ou Manuel)."""
        
        # 1. Tentative de reconnexion auto
        if self.device_address:
            print(f"\n🔄 Tentative de reconnexion à {self.device_name} ({self.device_address})...")
            try:
                self.client = BleakClient(self.device_address)
                await self.client.connect()
                print("✅ Reconnexion réussie !")
                self.is_connected = True
                
                if not self.midi_uuid:
                    # Si on a l'adresse mais pas l'UUID (cas rare), on lance la sélection
                    self.midi_uuid = await self.select_characteristic()
                    self.save_config()
                return True
            except Exception as e:
                print(f"⚠️ Échec reconnexion ({e}). On relance un scan.")
                self.device_address = None # Reset pour forcer le scan
        
        # 2. Sélection manuelle Appareil
        device = await self.select_device()
        if not device: return False
        
        self.device_address = device.address
        self.device_name = device.name or "Piano Inconnu"
        
        # 3. Connexion
        print(f"🔗 Connexion à {self.device_name}...")
        try:
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            self.is_connected = True
            print("✅ Connecté.")
        except Exception as e:
            print(f"❌ Impossible de se connecter : {e}")
            return False

        # 4. Sélection manuelle UUID (Diagnostic)
        self.midi_uuid = await self.select_characteristic()
        if not self.midi_uuid: return False
        
        # 5. Sauvegarde
        self.save_config()
        return True

    async def send_midi_message(self, msg):
        """Envoie le message MIDI via l'UUID configuré."""
        if not self.is_connected or not self.midi_uuid:
            return

        if msg.type not in ['note_on', 'note_off', 'control_change']:
            return

        # Format BLE MIDI: Header(0x80) + Timestamp(0x80) + RawMidi
        midi_bytes = msg.bytes()
        packet = bytearray([0x80, 0x80] + midi_bytes)
        
        try:
            await self.client.write_gatt_char(self.midi_uuid, packet)
        except Exception as e:
            print(f"⚠️ Erreur envoi : {e}")

    async def play_file(self, filename):
        filepath = os.path.join(MIDI_FOLDER, filename)
        try:
            mid = mido.MidiFile(filepath)
            print(f"\n▶️  Lecture de : {filename}")
            print("   [ESPACE]=Pause/Reprise | [R]=Rembobiner | [S]=Stop/Changer fichier")
        except Exception as e:
            print(f"❌ Erreur lecture fichier : {e}")
            return

        self.stop_requested = False
        self.rewind_requested = False
        self.is_paused = False
        
        while True:
            # On utilise le générateur mido pour le timing
            playback = mid.play(meta_messages=True)
            
            for msg in playback:
                if self.stop_requested: return
                
                # Gestion du Rewind
                if self.rewind_requested:
                    print("\n⏪ Rembobinage...")
                    self.rewind_requested = False
                    break # Break le for pour relancer le while

                # Gestion de la Pause
                while self.is_paused:
                    if self.stop_requested: return
                    if self.rewind_requested: break
                    await asyncio.sleep(0.1)
                
                # Check rewind après pause
                if self.rewind_requested:
                    print("\n⏪ Rembobinage...")
                    self.rewind_requested = False
                    break

                # Envoi
                if not msg.is_meta:
                    await self.send_midi_message(msg)
            else:
                print("\n🏁 Fin du morceau.")
                return

    async def input_listener(self):
        while True:
            if self.stop_requested and not self.is_paused:
                await asyncio.sleep(1)
                continue
            
            try:
                cmd = await ainput("")
                cmd = cmd.lower().strip()

                if cmd == 's':
                    print("🛑 Stop...")
                    self.stop_requested = True
                elif cmd == 'r':
                    self.rewind_requested = True
                elif cmd == '' or cmd == 'p':
                    self.is_paused = not self.is_paused
                    print(f"   {'⏸️ PAUSE' if self.is_paused else '▶️ LECTURE'}")
            except:
                pass

async def main():
    if not os.path.exists(MIDI_FOLDER):
        os.makedirs(MIDI_FOLDER)
        print(f"📁 Dossier '{MIDI_FOLDER}' créé.")

    controller = PianoController()
    
    # Lancement du SETUP (Connexion + Config)
    if not await controller.setup():
        print("❌ Configuration échouée. Arrêt.")
        return

    # Lancement de l'écoute clavier
    asyncio.create_task(controller.input_listener())

    # Boucle Menu
    while True:
        files = [f for f in os.listdir(MIDI_FOLDER) if f.endswith('.mid')]
        
        if not files:
            print(f"⚠️ Aucun fichier .mid dans '{MIDI_FOLDER}'. Ajoutez-en !")
            await asyncio.sleep(3)
            continue

        print("\n--- MENU MIDI ---")
        for i, f in enumerate(files):
            print(f"[{i+1}] {f}")
        print("[Q] Quitter")
        print("[C] Reconfigurer (Oublier connexion actuelle)")

        choice = await ainput("\nChoix : ")
        
        if choice.lower() == 'q':
            break
        elif choice.lower() == 'c':
            # Suppression config et restart setup
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            print("♻️  Configuration effacée. Relance du scan...")
            controller.device_address = None
            controller.midi_uuid = None
            await controller.client.disconnect()
            if not await controller.setup(): break
            continue

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                await controller.play_file(files[idx])
            else:
                print("Numéro invalide.")
        except ValueError:
            print("Commande invalide.")

    if controller.client:
        await controller.client.disconnect()
        print("Déconnecté.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt.")