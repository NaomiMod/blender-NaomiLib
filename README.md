# Blender NaomiLib importer Addon

NaomiLib is a graphic format developed by AM2 division, extensively used by SEGA between 1999-2001 in SEGA Naomi arcade hardware and SEGA Dreamcast.
Currently there are two known NaomiLib versions: NLOBJPUT Ver.0.99 and 0.8

Check out our Wiki if you're looking for [model format](https://github.com/NaomiMod/NL-ModelFormat/wiki)!

NaomiLib format has been researched by VincentNL for the initial purpose of creating custom 3D models in Virtua Tennis (Virtua Merdaio). Upon completing the model structure research, Vincent eventually met TheZocker on Blender Script Discord channel and thanks to TheZocker immense Blender & Python coding skills, their cooperation eventually led to the present addon.
The release version is able to open 3D models in NL format and variation used by Super Monkey Ball on Gamecube.

# Features

- Loads 3D models with original texture U/V

Import function has three options:

1. Clean scene (Clean up the current scene before import)
2. Scale factor (Especially useful to reduce Super / Monkey Balls huge 3D backgrounds)
3. Lz_p (3D model containers used by Super Monkey Ball on GameCube)

![alt text](https://i.imgur.com/dg4QDzU.png)

# Contacts / Bug Reports:

This addon is currently in WIP status, new features and games will be added to the list as we gather new data.

Before reporting an issue please check this out:

1. Please take note that at the present time only single models or archives are supported. if you want to load models conposed by multiple files, you need to import them without ticking the `Clean scene box`.
   We also suggest using F3 shortcut to bring up a  `recent commands` menu in Blender, by searching for `bin`, will bring NaomiLib name and import screen immediately.
2. RGB / Transparency / Reflectiveness is not imported yet.
3. You cannot export models in NL format.
4. We do not distribute any game model / textures. You will have to legally dump your own games and extract files from it. Specific extractors are provided on a dedicate [Game Extraction Tools](https://github.com/NaomiMod/games-ExtractTools) section.
If you want to help us out in finding new games supporting NL, find any bug or errors in loading models, please reach me out on Discord: **Vincent#5259

# Disclaimer

This project is intended exclusively for educational purposes and has no affiliation with SEGA or any other third party developer. NaomiLib format, NLOBJPUT and games using it are exlusive property of SEGA. Blender NaomiLib importer Addon is a recreative project, no compensation has been offered for research and will not be accepted in any form.

## Supported games

| Game                                       | Device                  |
| ------------------------------------------ | ----------------------- |
| 18 Wheeler: American Pro Trucker           | SEGA DREAMCAST          |
| Cannon Spike                               | SEGA DREAMCAST          |
| Cosmic Smash                               | SEGA DREAMCAST          |
| Crazy Taxi                                 | SEGA DREAMCAST          |
| Crazy Taxi 2                               | SEGA DREAMCAST          |
| Daytona USA 2001                           | SEGA DREAMCAST          |
| Dead or Alive 2                            | SEGA DREAMCAST          |
| Dead or Alive 2 - Prototype (27 JAN 2000)  | SEGA DREAMCAST          |
| Ferrari F355 Challenge                     | SEGA DREAMCAST          |
| Fighting Vipers 2                          | SEGA DREAMCAST          |
| Giant Gram 2000: All-Japan Pro Wrestling 2 | SEGA DREAMCAST          |
| Giant Gram 2000: All-Japan Pro Wrestling 3 | SEGA DREAMCAST          |
| House of The Dead 2                        | SEGA DREAMCAST          |
| Outtrigger                                 | SEGA DREAMCAST          |
| Power Stone 2                              | SEGA DREAMCAST          |
| Shenmue 2                                  | SEGA DREAMCAST          |
| Sports Jam                                 | SEGA DREAMCAST          |
| Virtua Fighter 3tb                         | SEGA DREAMCAST          |
| Virtua Tennis / Power Smash                | SEGA DREAMCAST          |
| Virtua Tennis 2 / Power Smash 2            | SEGA DREAMCAST          |
| Cannon Spike                               | ARCADE NAOMI            |
| Mobile Suit Gundam: Federation vs. Zeon    | ARCADE NAOMI            |
| House of The Dead 2                        | ARCADE NAOMI            |
| Outtrigger                                 | ARCADE NAOMI            |
| Project Justice                            | ARCADE NAOMI            |
| Spikers Battle                             | ARCADE NAOMI - GDS-0005 |
| Monkey Ball                                | ARCADE NAOMI - GDS-0008 |
| Ninja Assault                              | ARCADE NAOMI            |
| SEGA Marine Fishing                        | ARCADE NAOMI            |
| SPAWN - In The Demon's Hand                | ARCADE NAOMI            |
| The Typing of the Dead                     | ARCADE NAOMI            |
| World Kicks                                | ARCADE NAOMI            |
| Virtua Tennis / Power Smash                | ARCADE NAOMI - GDS-0011 |
| Zero Gunner 2                              | ARCADE NAOMI            |
| Zombie Revenge                             | ARCADE NAOMI            |
| Marvel Vs Capcom 2                         | ARCADE NAOMI            |
| Capcom Vs Snk 2                            | ARCADE NAOMI            |


## How to install

- download latest release from the [release](https://github.com/zocker-160/blender-NaomiLib/releases) page
- install zip as addon in Blender in the preferences

## How to build

If you want to build the Blender package on your own, run following commands:

```bash
git clone https://github.com/zocker-160/blender-NaomiLib.git
cd blender-NaomiLib
make
```

Install the addon into Blender using the created zip package

## Supported Blender versions:

- Blender 2.83 LTS
- Blender 2.90

## Special Thanks to:

- Deo , Kobainkurt , Lenders18 , Melfice , TheBosZ, Merdaio
