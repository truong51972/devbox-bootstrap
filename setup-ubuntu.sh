#!/bin/bash

# If we are not running in a local repository directory, bootstrap automatically
if [ ! -f "utils/utils.sh" ]; then
    echo "=========================================================="
    echo "  Ubuntu Setup: Bootstrapping from remote repository...   "
    echo "=========================================================="

    # Ensure git is installed
    if ! command -v git &> /dev/null; then
        echo "Git is not installed. Installing git..."
        sudo apt-get update && sudo apt-get install -y git
    fi

    # Create a temporary directory
    TEMP_DIR=$(mktemp -d /tmp/setup-ubuntu.XXXXXX)

    # Clone the repository
    echo "Cloning setup repository..."
    git clone --depth 1 https://github.com/truong51972/devbox-bootstrap.git "$TEMP_DIR"

    # Run the setup script in the cloned directory
    echo "Running setup script..."
    cd "$TEMP_DIR"

    # Use /dev/tty for stdin if available to allow interactive prompts
    if [ -t 0 ] || [ -c /dev/tty ]; then
        bash setup-ubuntu.sh "$@" < /dev/tty
    else
        bash setup-ubuntu.sh "$@"
    fi

    # Clean up the temporary directory
    echo "Cleaning up temporary files..."
    cd - > /dev/null
    rm -rf "$TEMP_DIR"
    exit 0
fi

source utils/utils.sh

source installers/basic.sh
read -p "$(color_text "Install zsh and oh-my-zsh? (y/n): " "green")" install_zsh
if [ "$install_zsh" = "y" ] || [ "$install_zsh" = "Y" ]; then
    source installers/zsh.sh
    source installers/powerlevel10k.sh
fi

source installers/keychain.sh
source installers/python.sh

read -p "$(color_text "Install docker? (y/n): " "green")" create_key
if [ "$create_key" = "y" ] || [ "$create_key" = "Y" ]; then
    source installers/docker.sh

    read -p "$(color_text "Install nvidia container toolkit? (y/n): " "green")" nvtoolkit
    if [ "$nvtoolkit" = "y" ] || [ "$nvtoolkit" = "Y" ]; then
        source installers/nvidia-container-toolkit.sh
    fi
fi

source installers/zoxide.sh
source installers/k8s.sh

source installers/clean.sh