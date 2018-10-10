# -*- coding: utf-8 -*-
# Copyright (c) 2018 Renat R. Dusaev <crank@qcrypt.org>
# Author: Renat R. Dusaev <crank@qcrypt.org>
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
Filesystem tree creating routine.
"""
#                               *** *** ***
import os, sys, logging, argparse, yaml
import lamia.logging \
     , lamia.core.templates \
     , lamia.core.filesystem \
     , lamia.core.task
import lamia.routines.render
#                               *** *** ***
gCommonParameters = {
    'fstruct,f' : {
        'help' : "File structure template to render.",
    },
    'path_context' : {
        'help' : "Path context stack description. May be a file to be added"
            " in context stack, or alias: @fContext (for file template"
            " context), @user (for user-defined variables).",
        'action' : 'append',
        'dest' : 'path_contexts'
    },
    'path_def,P' : {
        'help' : "Path context entry definition. Similar to -D for"
            " file-template context: adds a definition within the path"
            " template rendering context. Expected to be in form"
            " <name>=<vale>.",
        'type' : lamia.core.configuration.conf_arg_expr,
        'action' : 'append',
        'dest' : 'path_definitions'
    },
    'fstruct_conf' : {
        'help' : "Section name, within fstruct doc to use."
    }
    # TODO:
    #'diff' : {
    #   'help' : 'A flag. When given, makes'
    #       ' template-rendering engine display differencies between existing'
    #        ' subtree and rendered one instead of subtree (re-)creation.'
    #        , 'action' : 'store_true'
    # }
}
gExecParameters = {
    'output_dir,o' : {
        'help' : "Base directory where subtree must be created."
    }
}
gDefaults = {
    'path_contexts' : [],
    'output_dir' : os.getcwd(),
    'path_definitions' : [],
    'fstruct_conf' : 'default'
}
gEpilog="""
To make use of this procedure one need a special definition
of filesystem subtree to be deployed.
Note, that `--path-def'" entries will not take effect unless --path-ctx=@user is
specified.
"""
#                               *** *** ***
class DeploySubtreeTask( lamia.routines.render.RenderTemplateTask
                       , metaclass=lamia.core.task.TaskClass ):
    """
    A Lamia's task subclass performing deployment of some filesystem subtree.
    An effective subtree structure and templates have to be supplied by user
    presets.
    """
    __commonParameters=gCommonParameters
    __execParameters=gExecParameters
    __defaults=gDefaults
    __epilog=gEpilog

    def setup_path_templating( self
                             , pathContexts
                             , pathDefinitions ):
        self.pStk = lamia.core.configuration.compose_stack(pathContexts, pathDefinitions)

    @staticmethod
    def parse_fstruct( fstruct
                     , fstructConf
                     , pathInterpCtx={} ):
        """
        Returns object that typically consumed by lamia.core.filesystem.Paths
        instance constructor.
        """
        L = logging.getLogger(__name__)
        fStrObj = None
        if type(fstruct) is str:
            m = lamia.core.filesystem.rxFmtPat.match(fstruct.format(**pathInterpCtx))
            if m:
                if hasattr( self, 'pStk' ):
                    fstruct = fstruct.format(**self.pStk)
                else:
                    L.error('Path "%s" seems to contain formatting pattern'
                            ' but no path-formatting context being set at the'
                            ' moment.'%fstruct )
            with open(fstruct) as f:
                fStrObj = yaml.load(f)
        else:
            fStrObj = yaml.load(fstruct)
        fStrVer = fStrObj.get('version', '0.0')
        if '0.0' != 'version':  # TODO: finer versions control
            L.warning( "File structure version %s might be"
                    " unsupported (file \"%s\")."%(fStrVer, fstruct.name \
                            if hasattr(fstruct, 'name') else fstruct) )
        fStrObj = fStrObj[fstructConf]
        if not if fStrObj[fstructConf]:
            raise RuntimeError("Empty file structure subtree description.")
        if 'extends' in fStrObj.keys():
            base = DeploySubtreeTask.parse_fstruct( fStrObj['extends']['path'].format(**pathInterpCtx)
                                                  , fStrObj['extends'].get('conf', 'default') )
            base.update(fStrObj)
            fStrObj = base
        return fStrObj

    def setup_rendering( self
                       , templatesDirs
                       , contexts
                       , definitions=[]):
        """
        Overrides vanilla template-rendering set-up to support template paths
        for template directories.я
        """
        if hasattr(self, 'pStk'):
            assert(type(templatesDirs) is list)
            for n, p in enumerate(templatesDirs):
                if lamia.core.filesystem.rxFmtPat.match(p):
                    templatesDirs[n] = p.format(**self.pStk)
        super().setup_rendering( templatesDirs
                               , contexts
                               , definitions=definitions)

    def _main( self
             , outputDir=None
             , fstruct=None
             , fstructConf='default'
             , contexts=[], definitions=[]
             , pathContexts=[], pathDefinitions=[]
             , templatesDirs=[]
             , showDiff=False ):
        """
        Single function performing rendering of the subtree. Arguments:
        @outputDir -- defines the base (target) directory where subtree has to
            be created.
        @fstruct -- the subtree description (path to YAML doc or ready object).
        @fstructConf -- defines the particular section within the @fstruct
            document
        @contexts -- additional contexts for templates rendering
        @definitions -- additional variable definitions for templates rendering
        @pathContexts -- additional contexts for path templates
        @pathDefinitions -- aditional definitions for path context
        @templatesDirs -- templates directory to consider
        Returns:
            - instance of lamia.core.templates.Templates used to render templates
              and actually deploy the subtree;
            - instance of lamia.core.filesystem.Paths describing files subtree;
            - runtime contexts stack
            - path contexts stack
            - interpolators
            - filters
        Note: probably, pointless. We usually need to perform some operations in
        between of path template-rendering and generating the actual subtree.
        """
        assert(outputDir)
        assert(fstruct)
        self.setup_path_templating( pathContexts, pathDefinitions )
        self.fstruct = lamia.core.filesystem.Paths(self.parse_fstruct( fstruct, fstructConf ))
        self.setup_rendering( templatesDirs, contexts, definitions )
        self.t.deploy_fs_struct( outputDir
                          , self.fstruct
                          , self.pStk
                          , templateContext=self.rStk )
#                               *** *** ***
if "__main__" == __name__:
    lamia.logging.setup()
    t = DeploySubtreeTask()
    sys.exit(t.run())

