#!/bin/bash

source ~/scripts/api_key

tar -cf - *.{fits,xisf} | curl --resolve upload.patrick115.eu:443:185.158.65.124 -X POST --data-binary @- "https://upload.patrick115.eu/api/folder/a306f0b8-9e0b-411c-b5a3-b5d00d4ec45e?token=$API_KEY"
