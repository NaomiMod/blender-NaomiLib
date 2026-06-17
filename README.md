# Blender NaomiLib Addon

Naomi Library is a 3D graphics format developed by AM2, extensively used by SEGA between 1999–2001 on SEGA Naomi / Naomi 2 arcade hardware and SEGA Dreamcast. There are two known main versions: **Ver.0.99** and **0.8**.

Check out the Wiki for the [model format reference](https://github.com/NaomiMod/NL-ModelFormat/wiki).

Naomi Library was initially reverse engineered by VincentNL while modding Virtua Tennis. The first importer was developed by TheZocker, with TVIndustries joining the team shortly after.

Research by Egregiousguy, MetalliC, and CyoTheVile's Naomi SDK release — which included Naomi 2 model format data — completed the picture and made the exporter possible. The addon supports NL/NL2 import and export, plus the variant used by Super Monkey Ball on GameCube.

---

## Supported Blender versions

- Blender 5.x
- Blender 4.x

---

## Features

### Importer

Imports `.bin` and `.lz_p` Naomi Library files (File → Import → NaomiLib).

Options:

- **Scale** — uniform scale applied on import
- **Forward / Up axis** — configurable axis orientation (`-Y` forward / `+Z` up by default, matching standard NaomiLib export)
- **Import directory** — import every `.bin` / `.lz_p` file in the selected folder at once
- **Multi-file select** — select several individual files in the browser
- **Clear scene** — remove all objects and collections before import
- **Weld vertices** — merge strip-boundary duplicate vertices (forces normal recalculation)
- **Import normals** — store hardware normals from the binary; when off, Blender recalculates them
- **Debug output** — print strip and vertex info to the log

Each imported collection stores the source file path and a CRC32 checksum, enabling the **Update Model File** feature.

---

### Exporter

Exports collections to `.bin` Naomi Library format (File → Export → NaomiLib).

Options:

**Presets** — save, load, and delete named export configurations. Presets cover all settings below so you can switch between game targets in one click.

**General**

- **Index** — Auto (uses Global Parameters 0), Super, or Beta index format
- **Search level** — strip-search quality from 0 (fastest) to 4 (deepest)
- **Rebuild script** — run a custom script from the `rebuild_scripts/` folder after export (e.g. to repack an AFS archive)

**Geometry**

- **Forward / Up axis** — axis remapping on export (matches importer defaults)
- **Scale** — uniform output scale
- **Optimize Geometry** — merge duplicate vertices, triangulate, and fix non-manifold edges in memory; the source mesh is never modified

**Polygons**

- **No Independent Triangles** — suppress triangle tables
- **All Triangles** — force triangle output
- **Split Polygons** — triangulate n-gons
- **Adjust UV** — shrink oversized UV values

**Texture**

- **Encode PVRs** — encode all Texture Manager images to `.PVR` before export using their assigned format; skips textures whose pixel data already matches the existing `.PVR` on disk
- **Merge (model)** — merge identical materials across the model
- **Merge (nearby)** — merge materials on nearby geometry

**Advanced**

- **Export All** — export every Naomi Library collection in the scene to a folder, one `.bin` per collection
- **Naomi2** — output in NAOMI2 (NL2) format

---

### Update Model File

**Update Model File** writes your mesh edits back to the original imported `.bin` without re-running the exporter dialog.

The button appears in the **Collection Properties → Naomi Global Parameters** panel whenever the active collection was imported via the Naomi Library importer. It shows the source filename and a **Recalculate Centroid** toggle.

Clicking it overwrites the original file in place and refreshes the stored CRC32. Because the update preserves the original model structure without altering geometry counts or topology, it is safe to modify vertex positions and texture assignments on any original model while keeping full game compatibility. Import once, edit, update, done.

---

### Texture Manager

The Texture Manager panel (available on the active object in the N-panel or Properties) manages the texture set for a Naomi Library collection.

- **UIList** with thumbnail previews, Texture ID, format (`TexFmt` / `PixFmt`), and mipmap toggle per slot
- **Add Texture** — add one or more image files at once (multi-select supported)
- **Replace Image** — swap the image for an existing slot
- **Delete Image** — remove a slot and its companion `.PVR` / `.PVP` files
- **Encode PVR** — encode all images to `.PVR` immediately using per-slot format settings
- **Change Image Folder** — relocate the texture folder
- **Refresh** — rescan the folder and rebuild the list, re-reading `.PVR` headers to restore format settings automatically
- **Drag-scroll** — click-and-drag to scroll the list on large texture sets

Format settings (`TexFmt` / `PixFmt`) are read automatically from existing `.PVR` headers on refresh; when no `.PVR` is present the best format is inferred from the image content.

---

### Material Presets (Naomi Properties panel)

One-click material setup buttons assign the correct Blender shader nodes and Naomi TSP flags for each hardware rendering mode:

| Preset | Description |
| --- | --- |
| **Lambert** | Standard diffuse with texture |
| **Flat** | Flat-shaded, no lighting |
| **Vertex Colors** | Per-vertex color (no texture) |
| **Env Map** | Environment / reflection mapping (`nlObjPutCheapEnvMap`) |
| **Palette** | 4-BPP or 8-BPP indexed palette texture |
| **Bump Map** | Two-pass bump/normal map |

Each preset sets correct default blend modes (SRC / DST alpha), texture alpha, fog, color clamp, UV clamping, and filter mode. Individual TSP fields can be overridden per-object via the **Naomi Properties** panel.

Additional per-object actions:

- **Copy / Paste Naomi Properties** — transfer all TSP settings between objects
- **Export / Import Naomi Object Props (.json)** — save and load per-object settings to disk
- **Set Partner Mesh** — link a second mesh for two-pass effects (bump map, transparency pairs)
- **Set / Reset Palette ID** — assign the palette file index (`PalID_XXX`)
- **Apply Selected Texture ID** — push the active Texture Manager slot ID to the selected object

---

### Global Parameters (Collection Properties)

Each collection stores **Global Parameters 0** and **Global Parameters 1**, controlling index format and rendering flags (environment map, palette texture, bump map) at the collection level. The panel also displays the **OBJ Centroid Data** (X / Y / Z / bound radius), which is recalculated automatically on export when **Recalculate Centroid** is enabled.

---

## Installation

1. Download the latest release from the [Releases](https://github.com/NaomiMod/blender-NaomiLib/releases) page.
2. In Blender go to **Edit → Preferences → Add-ons → Install** and select the downloaded `.zip`.
3. Enable the addon.

Textures are loaded automatically from a `Textures/` subfolder placed alongside the `.bin` file (`.png` and `.tga` supported).

---

## How to build

```bash
git clone https://github.com/zocker-160/blender-NaomiLib.git
cd blender-NaomiLib
make
```

Install the resulting `.zip` package via Blender Preferences.

---

## Supported games

| Game | Device |
| --- | --- |
| 18 Wheeler: American Pro Trucker | SEGA DREAMCAST |
| Cannon Spike | SEGA DREAMCAST |
| Cosmic Smash | SEGA DREAMCAST |
| Crazy Taxi | SEGA DREAMCAST |
| Crazy Taxi 2 | SEGA DREAMCAST |
| Daytona USA 2001 | SEGA DREAMCAST |
| Dead or Alive 2 | SEGA DREAMCAST |
| Dead or Alive 2 - Prototype (27 JAN 2000) | SEGA DREAMCAST |
| Ferrari F355 Challenge | SEGA DREAMCAST |
| Fighting Vipers 2 | SEGA DREAMCAST |
| Giant Gram 2000: All-Japan Pro Wrestling 2 | SEGA DREAMCAST |
| Giant Gram 2000: All-Japan Pro Wrestling 3 | SEGA DREAMCAST |
| House of The Dead 2 | SEGA DREAMCAST |
| Outtrigger | SEGA DREAMCAST |
| Power Stone 2 | SEGA DREAMCAST |
| Shenmue 2 | SEGA DREAMCAST |
| Sports Jam | SEGA DREAMCAST |
| Virtua Fighter 3tb | SEGA DREAMCAST |
| Virtua Tennis / Power Smash | SEGA DREAMCAST |
| Virtua Tennis 2 / Power Smash 2 | SEGA DREAMCAST |
| Cannon Spike | ARCADE NAOMI |
| Mobile Suit Gundam: Federation vs. Zeon | ARCADE NAOMI |
| House of The Dead 2 | ARCADE NAOMI |
| Outtrigger | ARCADE NAOMI |
| Project Justice | ARCADE NAOMI |
| Spikers Battle | ARCADE NAOMI - GDS-0005 |
| Monkey Ball | ARCADE NAOMI - GDS-0008 |
| Ninja Assault | ARCADE NAOMI |
| SEGA Marine Fishing | ARCADE NAOMI |
| SPAWN - In The Demon's Hand | ARCADE NAOMI |
| The Typing of the Dead | ARCADE NAOMI |
| World Kicks | ARCADE NAOMI |
| Virtua Tennis / Power Smash | ARCADE NAOMI - GDS-0011 |
| Zero Gunner 2 | ARCADE NAOMI |
| Zombie Revenge | ARCADE NAOMI |
| Marvel Vs Capcom 2 | ARCADE NAOMI |
| Capcom Vs Snk 2 | ARCADE NAOMI |
| Super Monkey Ball | GAMECUBE |

---

## Bug reports & contacts

This addon is in active development. Before reporting an issue:

1. To load all models in a folder, tick **Import directory** before importing.
2. Textures are auto-loaded from a `Textures/` folder next to the model file.
3. To swap a texture on a model, change the Texture ID in the Naomi Properties panel or use the Texture Manager.
4. We do not distribute game models or textures. You must legally dump your own games and extract files yourself. Extractors are provided in the [Game Extraction Tools](https://github.com/NaomiMod/games-ExtractTools) repository.

Discord: **Vincent#5259**

---

## Disclaimer

This project is intended exclusively for educational purposes and has no affiliation with SEGA or any other third-party developer. Naomi Library is an exclusive property of SEGA. This addon is a recreational project; no compensation has been offered for the research and none will be accepted in any form.

---

## Credits

**Support and testing**

- Esppiral
- LeoBun
- Alexvgz
- Rob2d

## Special thanks

- Deo
- Kobainkurt
- Lenders18
- Melfice
- TheBosZ
- Merdaio
- NaomiMod Discord
