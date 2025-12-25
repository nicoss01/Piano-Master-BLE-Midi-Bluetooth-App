# 🎹 Piano Bluetooth Master v3.0

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()
[![Bluetooth](https://img.shields.io/badge/Bluetooth-LE%20MIDI-blueviolet)]()

**Piano Bluetooth Master** est une application de bureau moderne écrite en Python qui permet de visualiser des fichiers MIDI sous forme de partition déroulante et d'interagir avec un piano numérique via Bluetooth (BLE MIDI).

Elle est conçue pour l'apprentissage, offrant un mode "Pas à pas" qui attend que vous jouiez la bonne note sur votre piano avant d'avancer.

---

## 🇫🇷 Français

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
    git clone [https://github.com/votre-username/piano-bluetooth-master.git](https://github.com/votre-username/piano-bluetooth-master.git)
    cd piano-bluetooth-master
    ```

2.  Installez les dépendances nécessaires :
    ```bash
    pip install customtkinter bleak mido
    ```

### 🚀 Utilisation

1.  Lancez l'application :
    ```bash
    python gui.py
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
    git clone [https://github.com/your-username/piano-bluetooth-master.git](https://github.com/your-username/piano-bluetooth-master.git)
    cd piano-bluetooth-master
    ```

2.  Install the required libraries:
    ```bash
    pip install customtkinter bleak mido
    ```

### 🚀 Usage

1.  Run the script:
    ```bash
    python gui.py
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