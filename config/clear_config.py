# clear_config.py
# called by clear_config to clear all interface.ini values
# and to clear all multischeduler.ini values other than those in TIMING


import configparser
import sys

path = sys.argv[1]
config = configparser.ConfigParser(comment_prefixes='/', allow_no_value=True)
config.read(path)
for section in ('DB', 'Q'):
    for key in config[section]:
        config[section][key]=''
    if 'SSH' in config: 
        config['SSH']['ssh_key']=''
with open(path, 'w') as fout:
    config.write(fout)
