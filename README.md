# pyraphyletic - a pyramid implementation of phylesystem-api

This is an untested port of the phylesystem-api from web2py to pyramid.

See https://github.com/OpenTreeOfLife/phylesystem-api/blob/master/docs/README.md for 
as description of the API.

We don't have an immediate plan to replace the web2py version with this one. (see http://irclog.perlgeek.de/opentreeoflife/2014-06-13 )

# Instructions

1. copy `development.ini.exmample` to `development.ini`

2. tweak the settings in `[app:main]` as you would for the web2py impl.

3. Launch the dev server.  For debugging, I like to use:

    $ while true ; do  pserve development.ini --reload ; sleep 5 ; done

to start an infinite loop of relaunching (server crashes on launch if you
have a SyntaxError)

# Credits

See CREDITS file for author list.

thanks to http://stackoverflow.com/questions/21107057/pyramid-cors-for-ajax-requests