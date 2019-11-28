#!/bin/bash

set -e

systemctl daemon-reload
systemctl enable cacophony-processing
systemctl restart cacophony-processing
