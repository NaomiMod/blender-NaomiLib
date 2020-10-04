# Blender NaomiLib importer Addon
NaomiLib is a 3D graphics format developed by AM2 division extensively used by SEGA on arcade games between 1999-2001, especially on SEGA Naomi arcade hardware and SEGA Dreamcast.
Currently there are 2 known revisions of the NaomiLib library, known as NLOBJPUT Ver.0.99 and 0.8

# Story
NaomiLib format has been extensively researched by Vincent for the initial purpose of creating custom 3D models in Virtua Tennis. Upon completing the model structure research, Vincent eve ntually met TheZocker on Blender Script Discord channel and thanks to TheZocker immense Blender & Python coding skills, their cooperation eventually led to the present addon.
The release version is able to open 3D models in NL format and variation used by Super Monkey Ball on Gamecube.

This addon is currently in WIP status, new games and features will be addressed as they are know 
If you find any bug or error in loading models, please reach me out on Discord! Vincent#5259

Addon has 3 import options:

Clean scene (To clean up the current scene before import)
Scale factor (Especially to reduce Monkey Ball huge 3D backgrounds)
Lz_p (3D model containres used by Super Monkey Ball on GameCube)

# Disclaimer
This project is intended exclusively for educational purposes and has no affiliation with SEGA or any other third party developer. NaomiLib format,NLOBJPUT and games using it are exlusive property of SEGA. Blender NaomiLib importer Addon is a recreative project, no compensation has been offered for research and will not be accepted in any form.



## Supported games

| Game                                        | Device                  |
| ------------------------------------------- | ----------------------- |
| 18 Wheeler: American Pro Trucker            | SEGA DREAMCAST          |
| Cosmic Smash                                | SEGA DREAMCAST          |
| Crazy Taxi                                  | SEGA DREAMCAST          |
| Crazy Taxi 2                                | SEGA DREAMCAST          |
| Dead or Alive 2 Ultimate                    | SEGA DREAMCAST          |
| Ferrari F355 Challenge                      | SEGA DREAMCAST          |
| Fighting Vipers 2                           | SEGA DREAMCAST          |
| Giant Gram 2000: All-Japan Pro Wrestling 2  | SEGA DREAMCAST          |
| Giant Gram 2000: All-Japan Pro Wrestling 3  | SEGA DREAMCAST          |
| Outtrigger                                  | SEGA DREAMCAST          |
| Power Stone 2                               | SEGA DREAMCAST          |
| Shenmue 2                                   | SEGA DREAMCAST          |
| Virtua Fighter 3tb                          | SEGA DREAMCAST          |
| Virtua Tennis / Power Smash                 | SEGA DREAMCAST          |
| Virtua Tennis 2 / Power Smash 2             | SEGA DREAMCAST          |
| Monkey Ball                                 | ARCADE NAOMI - GDS-0008 |
| Virtua Tennis / Power Smash                 | ARCADE NAOMI - GDS-0011 |





## How to install

- download latest release from the [release](https://github.com/zocker-160/blender-NaomiLib/releases) page
- intall zip as addon in Blender in the preferences

## How to build

If you want to build the Blender package on your own, run following commands:

```bash
git clone https://github.com/zocker-160/blender-NaomiLib.git
cd blender-NaomiLib
make
```

Install the addon into Blender using the created zip package
