# pyraphyletic - a pyramid implementation of phylesystem-api

This is an untested port of the phylesystem-api from web2py to pyramid.

See https://github.com/OpenTreeOfLife/phylesystem-api/blob/master/docs/README.md for 
as description of the API.

We don't have an immediate plan to replace the web2py version with this one. (see http://irclog.perlgeek.de/opentreeoflife/2014-06-13 )

# Instructions

## Prerequisites
This web app serves requests that interact with git-versioned data
The `repo_parent` setting in your `*.ini` file should be set 
to be the filepath of a directory (often called a "shards" directory
in Open Tree documentation) that is the parent of these git repos.

### Setting up repos
#### for testing
For any tests that check the ability of the phylesystem-api to push
new content to a remote version of the repositories, you'll need to a
fork of the testing repos:
  * https://github.com/snacktavish/mini_phyl
  * https://github.com/snacktavish/mini_system
  * https://github.com/jimallman/mini_amendments
  * https://github.com/jimallman/mini_collections

Assuming that you have cloned those to a git server such that the
repositories have those names and that the git clone prefix is 
common to all of them then you can bootstrap the local shards directory
to serve as your `repo_parent` setting using the `setup-testing-repos.bash`
script. For instance, @mtholder

  1. Sets a `PEYOTL_ROOT` environmental variable to point to the top
  of the peyotl repository.
   
  2. The he created a subdirectory inside of pyraphyletic called "shards"
  to serve as the repo parent by running:

    bash setup-local-testing-repos.bash shards git@github.com:mtholder

#### for a production or dev server
When deploying on a new machine that will act as  one of the Open 
Tree of Life's 2 servers you don't need to fork any repos to start the
process. You should be able to set up a new machine with:

    PEYOTL_ROOT="${HOME}/repo/peyotl" bash setup-dev-repos.bash "${HOME}/repo/dev-shards"
 
or

    PEYOTL_ROOT="${HOME}/repo/peyotl" bash setup-production-repos.bash "${HOME}/repo/production-shards"

Note: `peyotl` is a prerequisite of pyraphyletic, but the PEYOTL_ROOT 
variable is only needed for the `setup-*.bash` scripts

## Configuring pyraphyletic
1. copy `development.ini.example` to `development.ini`

2. tweak the settings in `[app:main]` as you would for the web2py impl.

3. Launch the dev server.  For debugging, I like to use:

    $ while true ; do  pserve development.ini --reload ; sleep 5 ; done

to start an infinite loop of relaunching (server crashes on launch if you
have a SyntaxError)

# Credits

See CREDITS file for author list.

thanks to http://stackoverflow.com/questions/21107057/pyramid-cors-for-ajax-requests