# Micro editor

You will help the user to modify the micro editor to create an excellent editor for editing python files in a large, professional codebase.

To achieve this goal you can modify the config of the user, the plugins of the user or the custom fork of the micro code for this user:

* Find the config at ~/config/micro
* Find the plugins at ~/config/micro_plugsin
* Find the Go code of the custom fork of the micro editor at ~/external/micro

The user is currently using the binary built in this fork, so remember that when you change the go code you will also need to rebuild the binary.

The config and plugins are symlinked to the correct places so they are also used by the editor.

You have the ability to test the micro editor interactively, so please do so when this is useful.

The user uses micro inside the Kitty terminal emulator, and uses the keyboard protocol so micro can use better keybindings.
