============================================================
 Sengoku Rance HD Patch (unofficial)
============================================================

A fan-made patch that raises the display resolution of the Steam
release of "Sengoku Rance" from 800x600 to 1600x1200.
In-game images and the OP/ED movies are generated from your own
game data by 2x AI upscaling.

This patch is an unofficial, non-commercial fan work and is not
affiliated with AliceSoft. Use it entirely at your own risk.

------------------------------------------------------------
 Requirements
------------------------------------------------------------

 * Sengoku Rance on Steam (vanilla / JP patch applied /
    Simplified Chinese build / English (Kagura) build)
 * DirectML-capable GPU recommended
   (not required, but first-time image generation takes a while)
 * About 9 GB of free space on the drive containing the game folder
   (working area + backup; the working area is deleted automatically
    when done)

------------------------------------------------------------
 Installation
------------------------------------------------------------

 1. Close the game, then run Install.cmd
    (the Steam install folder is detected automatically.
      Allow it if an administrator prompt appears)
 2. After a backup of the game is created automatically,
    AI generation of HD assets and the OP/ED movies begins
    (~10 minutes on a DirectML-capable GPU;
      measured ~9 min on Ryzen 9 5900X + RTX 3070 Ti)
 3. When "HD patch installed." appears, you are done

------------------------------------------------------------
 Uninstall
------------------------------------------------------------

 Run Uninstall.cmd.
 The game is fully restored from the created backup.

------------------------------------------------------------
 Notes
------------------------------------------------------------

 * Save data is not affected
 * The game cannot be running during installation
   (close it before running)
 * The hd_cache folder in the game folder is a cache of generated
   assets. Keeping it lets a future reinstall skip the generation
   step (you are asked whether to delete it on uninstall)
 * To update the patch to a new version, first revert with
   Uninstall.cmd, then install the new version
 * If you reinstall the game via Steam, just run Install.cmd again

------------------------------------------------------------
 License / bundled libraries
------------------------------------------------------------

 * Upscaling model:
   AnimeJaNai HD v3 Sharp1 UltraCompact (CC BY-NC-SA 4.0)
   See LICENSES\model.txt for details
 * alice-tools (GPL): bin\alice.exe
 * ffmpeg (GPL): bin\ffmpeg.exe (used only for movie upscaling)
   See LICENSES\ for details

 Report issues via Issues on the distribution page (GitHub
 repository).
