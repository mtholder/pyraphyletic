#!/usr/bin/env python
from peyotl.phylesystem.git_actions import GitAction
from peyotl.phylesystem import Phylesystem
from sh import git
import logging
import os
_LOG = logging.getLogger(__name__)

_PHYLESYSTEM = None
def get_phylesystem(settings):
    global _PHYLESYSTEM
    if _PHYLESYSTEM is not None:
        return _PHYLESYSTEM
    repo_parent = settings['repo_parent']
    git_ssh = settings.get('git_ssh', 'ssh')
    pkey = settings.get('pkey')
    git_hub_remote = settings.get('git_hub_remote', 'git@github.com:OpenTreeOfLife')
    push_mirror = os.path.join(repo_parent, 'mirror')
    pmi = {
        'parent_dir': push_mirror,
        'remote_map': {
            'GitHubRemote': git_hub_remote,
            },
    }
    mirror_info = {'push':pmi}
    _PHYLESYSTEM = Phylesystem(repos_par=repo_parent,
                               git_ssh=git_ssh,
                               pkey=pkey,
                               git_action_class=GitData,
                               mirror_info=mirror_info)
    _LOG.debug('repo_nexml2json = {}'.format(_PHYLESYSTEM.repo_nexml2json))
    return _PHYLESYSTEM

class GitData(GitAction):
    def __init__(self, repo, **kwargs):
        GitAction.__init__(self, repo, **kwargs)
    def delete_remote_branch(self, remote, branch, env={}):
        "Delete a remote branch"
        # deleting a branch is the same as
        # git push remote :branch
        self.push(remote, env, ":%s" % branch)

    def pull(self, remote, env={}, branch=None):
        """
        Pull a branch from a given remote

        Given a remote, env and branch, pull branch
        from remote and add the environment variables
        in the env dict to the environment of the
        "git pull" command.

        If no branch is given, the current branch
        will be updated.
        """
        if branch:
            branch_to_pull = branch
        else:
            branch_to_pull = self.current_branch()

        # if there is no PKEY, we don't need to override env
        # We are explicit about what we are pushing, since the default behavior
        # is different in different versions of Git and/or by configuration
        if env["PKEY"]:
            new_env = os.environ.copy()
            new_env.update(env)
            git(self.gitdir, self.gitwd, "pull", remote, "{}:{}".format(branch_to_pull,branch_to_pull), _env=new_env)
        else:
            git(self.gitdir, self.gitwd, "pull", remote, "{}:{}".format(branch_to_pull,branch_to_pull))

        new_sha      = git(self.gitdir, self.gitwd, "rev-parse","HEAD")
        return new_sha.strip()
