# clear_config.py

import configparser
import sys

path = sys.argv[1]
config = configparser.ConfigParser(inline_comment_prefixes='#')
config.read(path)
for section in ('DB', 'Q'):
    for key in config[section]:
        config[section][key]=''
    if 'SSH' in config: 
        config['SSH']['ssh_key']=''
with open(path, 'w') as fout:
    config.write(fout)
