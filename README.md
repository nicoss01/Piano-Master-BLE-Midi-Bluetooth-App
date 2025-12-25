# 🎹 Piano Bluetooth Master v3.0

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()
[![Bluetooth](https://img.shields.io/badge/Bluetooth-MIDI-blueviolet)]()

![](https://github.com/nicoss01/Piano-Master-BLE-Midi-Bluetooth-App/blob/main/screen.png?raw=true)

## 🌐 Language / Langue

- [🇬🇧 English Version](#-english)
- [🇫🇷 Version Française](#-français)

---

## 🇫🇷 Français


**Piano Bluetooth Master** est une application de bureau moderne écrite en Python qui permet de visualiser des fichiers MIDI sous forme de partition déroulante et d'interagir avec un piano numérique via Bluetooth (BLE MIDI).

Elle est conçue pour l'apprentissage, offrant un mode "Pas à pas" qui attend que vous jouiez la bonne note sur votre piano avant d'avancer.

---
### ✨ Fonctionnalités

* **Connexion Bluetooth Low Energy (BLE) :** Détection et connexion automatique aux pianos compatibles Bluetooth MIDI (Roland, Yamaha, Kawai, etc.).
* **Visualisation de Partition :**
    * Affichage déroulant (Rolling score).
    * Séparation automatique des mains : Clé de Sol (Main droite) / Clé de Fa (Main gauche) basée sur la hauteur des notes (Pivot à Do4).
    * Code couleur : Notes passées, actuelles et futures.
* **Modes de Lecture :**
    * **Lecture continue :** Écoute ou jeu par-dessus le fichier MIDI.
    * **Note par note (Step Mode) :** La lecture se met en pause jusqu'à ce que la note correcte soit détectée via l'entrée MIDI du piano.
    * **Boucle :** Répétition automatique du morceau.
* **Interface Moderne :** GUI sombre et fluide basée sur `CustomTkinter`.
* **Clavier Virtuel :** Visualisation en temps réel des touches actives.

### 🛠️ Prérequis

* Python 3.9 ou supérieur.
* Un adaptateur Bluetooth supportant le BLE.
* Un piano/clavier compatible MIDI Bluetooth.

### 📦 Installation

1.  Clonez ce dépôt :
    ```bash
    git clone [https://github.com/nicoss01/Piano-Master-BLE-Midi-Bluetooth-App.git](hhttps://github.com/nicoss01/Piano-Master-BLE-Midi-Bluetooth-App.git)
    cd piano-bluetooth-master
    ```

2.  Installez les dépendances nécessaires :
    ```bash
    pip install customtkinter bleak mido
    ```

### 🚀 Utilisation

1.  Lancez l'application :
    ```bash
    python main.py
    ```
2.  Cliquez sur **"Connecter Piano"** pour scanner et appairer votre instrument.
3.  Cliquez sur **"Ouvrir fichier MIDI"** pour charger une partition (`.mid`).
4.  Choisissez votre mode (Lecture continue ou Note par note) et appuyez sur Play (▶).

### ⚙️ Configuration
L'application crée automatiquement un fichier `piano_config.json` pour mémoriser le dernier appareil Bluetooth connecté et faciliter la reconnexion automatique.

---

## 🇬🇧 English

### ✨ Features

* **Bluetooth Low Energy (BLE) Connectivity:** Auto-discovery and connection to Bluetooth MIDI enabled pianos.
* **Sheet Music Visualization:**
    * Scrolling staff view.
    * Automatic hand splitting: Treble Clef (Right Hand) / Bass Clef (Left Hand) calculated dynamically.
    * Color coding: Past, current, and future notes.
* **Playback Modes:**
    * **Continuous Play:** Listen or play along with the MIDI file.
    * **Step-by-Step (Wait Mode):** Playback pauses and waits for you to press the correct key on your physical piano before advancing.
    * **Loop:** Repeat the track automatically.
* **Modern UI:** Sleek dark interface built with `CustomTkinter`.
* **Mini Keyboard:** Real-time visual feedback of active keys.

### 🛠️ Requirements

* Python 3.9 or higher.
* Bluetooth adapter with BLE support.
* Bluetooth MIDI compatible piano/keyboard.

### 📦 Installation

1.  Clone the repository:
    ```bash
    git clone [https://github.com/nicoss01/Piano-Master-BLE-Midi-Bluetooth-App.git](https://github.com/nicoss01/Piano-Master-BLE-Midi-Bluetooth-App.git)
    cd piano-bluetooth-master
    ```

2.  Install the required libraries:
    ```bash
    pip install customtkinter bleak mido
    ```

### 🚀 Usage

1.  Run the script:
    ```bash
    python main.py
    ```
2.  Click **"Connecter Piano"** (Connect Piano) to scan and pair your device.
3.  Click **"Ouvrir fichier MIDI"** (Open MIDI) to load a song (`.mid`).
4.  Select your mode (Continuous or Note-by-note) and hit Play (▶).

### ⚙️ Configuration
The app automatically creates a `piano_config.json` file to store the UUID of the last connected device, enabling auto-reconnection on the next launch.

---

## 🔧 Troubleshooting / Dépannage

**Bluetooth connection fails / Échec de connexion Bluetooth :**
* *Windows :* Ensure your device is paired in Windows Settings first if required, though `bleak` often handles direct connections.
* *Linux :* You might need to add your user to the `bluetooth` group and ensure `bluez` is installed.
* Make sure no other app is currently using the MIDI Bluetooth connection.

**Visualization lags / Ralentissements :**
* Resize the window. The canvas recalculates positions dynamically based on window size.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

## Compatibility Keyboard Models
- Yamaha EZ-300
- Yamaha EZ-220
- Yamaha EZ-115
- Yamaha Clavinova CSP-150
- Yamaha Clavinova CSP-170
- Yamaha Clavinova CSP-255
- Yamaha Clavinova CSP-275
- Yamaha Clavinova CSP-295
- Casio Casiotone LK-S450
- Casio Casiotone LK-S250
- Casio LK-265
- Casio LK-266
- Casio LK-136
- Casio LK-135
- Casio LK-190
- The ONE Smart Piano (Upright / Classic)
- The ONE Smart Keyboard Pro
- The ONE Light Keyboard Air
- The ONE COLOR
- ROLI Lumi Keys Studio Edition
- ROLI Lumi Keys 1
- PopuMusic PopuPiano
- Costway Clavier Pliable 88 Touches (Modèle LED)
- Costway Clavier Électronique 61 Touches (Modèle LED)
- Bora BX-20 (Piano Pliable 88 touches)
- Bora BX-10 (souvent rebadgé)
- Terence Piano Pliable 88 Touches (Modèle avec lumières)
- Longeye FOLD I (certaines versions ont les LED)
- Vangoa VGD-881
- Souidmy G-310W
- Alesis Melody 61 MKII
- RockJam RJ761
- Schubert Etude 450 USB
- Schubert Etude 300
- McGrey LK-6120
- FunKey 61 Edition Touch
- Glymnis Clavier Pliable 88 Touches
- Eastar EK-10S
- Donner DEK-610
- Starfavor SP-10
- Native Instruments Komplete Kontrol S49 (MK2 / MK3)
- Native Instruments Komplete Kontrol S61 (MK2 / MK3)
- Native Instruments Komplete Kontrol S88 (MK2 / MK3)