#!/bin/bash

source ~/scripts/api_key

curl -s "https://upload.patrick115.eu/api/folder/a306f0b8-9e0b-411c-b5a3-b5d00d4ec45e?token=$API_KEY" | tar -xf -
