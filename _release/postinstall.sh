#!/bin/bash

set -e

username=cacophony-processing
id $username &> /dev/null || useradd --system \
                                     --user-group \
                                     --groups docker \
                                     --home-dir /var/cache/$username \
                                     --create-home \
                                     --shell /usr/sbin/nologin \
                                     $username

systemctl daemon-reload
systemctl enable cacophony-processing
systemctl restart cacophony-processing
