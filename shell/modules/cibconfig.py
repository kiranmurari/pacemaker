# Copyright (C) 2008 Dejan Muhamedagic <dmuhamedagic@suse.de>
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

import sys
import subprocess
import copy
import xml.dom.minidom
import re

from singletonmixin import Singleton
from userprefs import Options, UserPrefs
from vars import Vars
from utils import *
from xmlutil import *
from msg import *
from parse import CliParser
from clidisplay import CliDisplay
from cibstatus import CibStatus

def id_in_use(obj_id):
    if id_store.is_used(obj_id):
        id_used_err(obj_id)
        return True
    return False

class IdMgmt(Singleton):
    '''
    Make sure that ids are unique.
    '''
    def __init__(self):
        self._id_store = {}
        self.ok = True # error var
    def new(self,node,pfx):
        '''
        Create a unique id for the xml node.
        '''
        name = node.getAttribute("name")
        if node.tagName == "nvpair":
            node_id = "%s-%s" % (pfx,name)
        elif node.tagName == "op":
            interval = node.getAttribute("interval")
            if interval:
                node_id = "%s-%s-%s" % (pfx,name,interval)
            else:
                node_id = "%s-%s" % (pfx,name)
        else:
            try:
                hint = hints_list[node.tagName]
            except: hint = ''
            if hint:
                node_id = "%s-%s" % (pfx,hint)
            else:
                node_id = "%s" % pfx
        if self.is_used(node_id):
            for cnt in range(99): # shouldn't really get here
                try_id = "%s-%d" % (node_id,cnt)
                if not self.is_used(try_id):
                    node_id = try_id
                    break
        self.save(node_id)
        return node_id
    def check_node(self,node,lvl):
        node_id = node.getAttribute("id")
        if not node_id:
            return
        if id_in_use(node_id):
            self.ok = False
            return
    def _store_node(self,node,lvl):
        self.save(node.getAttribute("id"))
    def _drop_node(self,node,lvl):
        self.remove(node.getAttribute("id"))
    def check_xml(self,node):
        self.ok = True
        xmltraverse_thin(node,self.check_node)
        return self.ok
    def store_xml(self,node):
        if not self.check_xml(node):
            return False
        xmltraverse_thin(node,self._store_node)
        return True
    def remove_xml(self,node):
        xmltraverse_thin(node,self._drop_node)
    def replace_xml(self,oldnode,newnode):
        self.remove_xml(oldnode)
        if not self.store_xml(newnode):
            self.store_xml(oldnode)
            return False
        return True
    def is_used(self,node_id):
        return node_id in self._id_store
    def save(self,node_id):
        if not node_id: return
        self._id_store[node_id] = 1
    def rename(self,old_id,new_id):
        if not old_id or not new_id: return
        if not self.is_used(old_id): return
        if self.is_used(new_id): return
        self.remove(old_id)
        self.save(new_id)
    def remove(self,node_id):
        if not node_id: return
        try:
            del self._id_store[node_id]
        except KeyError:
            pass
    def clear(self):
        self._id_store = {}

def filter_on_tag(nl,tag):
    return [node for node in nl if node.tagName == tag]
def nodes(node_list):
    return filter_on_tag(node_list,"node")
def primitives(node_list):
    return filter_on_tag(node_list,"primitive")
def groups(node_list):
    return filter_on_tag(node_list,"group")
def clones(node_list):
    return filter_on_tag(node_list,"clone")
def mss(node_list):
    return filter_on_tag(node_list,"master")
def constraints(node_list):
    return filter_on_tag(node_list,"rsc_location") \
        + filter_on_tag(node_list,"rsc_colocation") \
        + filter_on_tag(node_list,"rsc_order")
def properties(node_list):
    return filter_on_tag(node_list,"cluster_property_set") \
        + filter_on_tag(node_list,"rsc_defaults") \
        + filter_on_tag(node_list,"op_defaults")
def processing_sort(nl):
    '''
    It's usually important to process cib objects in this order,
    i.e. simple objects first.
    '''
    return nodes(nl) + primitives(nl) + groups(nl) + mss(nl) + clones(nl) \
        + constraints(nl) + properties(nl)

def obj_cmp(obj1,obj2):
    return cmp(obj1.obj_id,obj2.obj_id)
def filter_on_type(cl,obj_type):
    if type(cl[0]) == type([]):
        l = [cli_list for cli_list in cl if cli_list[0][0] == obj_type]
        l.sort(cmp = cmp)
    else:
        l = [obj for obj in cl if obj.obj_type == obj_type]
        l.sort(cmp = obj_cmp)
    return l
def nodes_cli(cl):
    return filter_on_type(cl,"node")
def primitives_cli(cl):
    return filter_on_type(cl,"primitive")
def groups_cli(cl):
    return filter_on_type(cl,"group")
def clones_cli(cl):
    return filter_on_type(cl,"clone")
def mss_cli(cl):
    return filter_on_type(cl,"ms") + filter_on_type(cl,"master")
def constraints_cli(node_list):
    return filter_on_type(node_list,"location") \
        + filter_on_type(node_list,"colocation") \
        + filter_on_type(node_list,"collocation") \
        + filter_on_type(node_list,"order")
def properties_cli(cl):
    return filter_on_type(cl,"property") \
        + filter_on_type(cl,"rsc_defaults") \
        + filter_on_type(cl,"op_defaults")
def ops_cli(cl):
    return filter_on_type(cl,"op")
def processing_sort_cli(cl):
    '''
    Return the given list in this order:
    nodes, primitives, groups, ms, clones, constraints, rest
    Both a list of objects (CibObject) and list of cli
    representations accepted.
    '''
    return nodes_cli(cl) + primitives_cli(cl) + groups_cli(cl) + mss_cli(cl) + clones_cli(cl) \
        + constraints_cli(cl) + properties_cli(cl) + ops_cli(cl)

def is_resource_cli(s):
    return s in vars.resource_cli_names
def is_constraint_cli(s):
    return s in vars.constraint_cli_names

def referenced_resources_cli(cli_list):
    id_list = []
    head = cli_list[0]
    obj_type = head[0]
    if not is_constraint_cli(obj_type):
        return []
    if obj_type == "location":
        id_list.append(find_value(head[1],"rsc"))
    elif len(cli_list) > 1: # resource sets
        for l in cli_list[1][1]:
            if l[0] == "resource_ref":
                id_list.append(l[1][1])
    elif obj_type == "colocation":
        id_list.append(find_value(head[1],"rsc"))
        id_list.append(find_value(head[1],"with-rsc"))
    elif obj_type == "order":
        id_list.append(find_value(head[1],"first"))
        id_list.append(find_value(head[1],"then"))
    return id_list

def rename_id(node,old_id,new_id):
    if node.getAttribute("id") == old_id:
        node.setAttribute("id", new_id)
def rename_rscref_simple(c_obj,old_id,new_id):
    c_modified = False
    for attr in c_obj.node.attributes.keys():
        if attr in vars.constraint_rsc_refs and \
                c_obj.node.getAttribute(attr) == old_id:
            c_obj.node.setAttribute(attr, new_id)
            c_obj.updated = True
            c_modified = True
    return c_modified
def delete_rscref_simple(c_obj,rsc_id):
    c_modified = False
    for attr in c_obj.node.attributes.keys():
        if attr in vars.constraint_rsc_refs and \
                c_obj.node.getAttribute(attr) == rsc_id:
            c_obj.node.removeAttribute(attr)
            c_obj.updated = True
            c_modified = True
    return c_modified
def rset_uniq(c_obj,d):
    '''
    Drop duplicate resource references.
    '''
    l = []
    for rref in c_obj.node.getElementsByTagName("resource_ref"):
        rsc_id = rref.getAttribute("id")
        if d[rsc_id] > 1: # drop one
            l.append(rref)
            d[rsc_id] -= 1
    rmnodes(l)
def delete_rscref_rset(c_obj,rsc_id):
    '''
    Drop all reference to rsc_id.
    '''
    c_modified = False
    l = []
    for rref in c_obj.node.getElementsByTagName("resource_ref"):
        if rsc_id == rref.getAttribute("id"):
            l.append(rref)
            c_obj.updated = True
            c_modified = True
    rmnodes(l)
    l = []
    for rset in c_obj.node.getElementsByTagName("resource_set"):
        if len(rset.getElementsByTagName("resource_ref")) == 0:
            l.append(rset)
            c_obj.updated = True
            c_modified = True
    rmnodes(l)
    return c_modified
def rset_convert(c_obj):
    l = c_obj.node.getElementsByTagName("resource_ref")
    if len(l) != 2:
        return # eh?
    c_obj.modified = True
    cli = c_obj.repr_cli(format = -1)
    newnode = c_obj.cli2node(cli)
    if newnode:
        c_obj.node.parentNode.replaceChild(newnode,c_obj.node)
        c_obj.node.unlink()
def rename_rscref_rset(c_obj,old_id,new_id):
    c_modified = False
    d = {}
    for rref in c_obj.node.getElementsByTagName("resource_ref"):
        rsc_id = rref.getAttribute("id")
        if rsc_id == old_id:
            rref.setAttribute("id", new_id)
            rsc_id = new_id
            c_obj.updated = True
            c_modified = True
        if not rsc_id in d:
            d[rsc_id] = 0
        else: 
            d[rsc_id] += 1
    rset_uniq(c_obj,d)
    # if only two resource references remained then, to preserve
    # sanity, convert it to a simple constraint (sigh)
    cnt = 0
    for key in d:
        cnt += d[key]
    if cnt == 2:
        rset_convert(c_obj)
    return c_modified
def rename_rscref(c_obj,old_id,new_id):
    if rename_rscref_simple(c_obj,old_id,new_id) or \
            rename_rscref_rset(c_obj,old_id,new_id):
        err_buf.info("resource references in %s updated" % c_obj.obj_string())
def delete_rscref(c_obj,rsc_id):
    return delete_rscref_simple(c_obj,rsc_id) or \
        delete_rscref_rset(c_obj,rsc_id)
def silly_constraint(c_node,rsc_id):
    '''
    Remove a constraint from rsc_id to rsc_id.
    Or an invalid one.
    '''
    if c_node.getElementsByTagName("resource_ref"):
        # it's a resource set
        # the resource sets have already been uniq-ed
        return len(c_node.getElementsByTagName("resource_ref")) <= 1
    cnt = 0  # total count of referenced resources have to be at least two
    rsc_cnt = 0
    for attr in c_node.attributes.keys():
        if attr in vars.constraint_rsc_refs:
            cnt += 1
            if c_node.getAttribute(attr) == rsc_id:
                rsc_cnt += 1
    if c_node.tagName == "rsc_location":  # locations are never silly
        return cnt < 1
    else:
        return rsc_cnt == 2 or cnt < 2

def show_unrecognized_elems(doc):
    try:
        conf = doc.getElementsByTagName("configuration")[0]
    except:
        common_warn("CIB has no configuration element")
        return
    for topnode in conf.childNodes:
        if not is_element(topnode):
            continue
        if is_defaults(topnode):
            continue
        if not topnode.tagName in cib_topnodes:
            common_warn("unrecognized CIB element %s" % c.tagName)
            continue
        for c in topnode.childNodes:
            if not is_element(c):
                continue
            if not c.tagName in cib_object_map:
                common_warn("unrecognized CIB element %s" % c.tagName)

def get_comments(cli_list):
    if not cli_list:
        return []
    last = cli_list[len(cli_list)-1]
    try:
        if last[0] == "comments":
            cli_list.pop()
            return last[1]
    except: pass
    return []

def lines2cli(s):
    '''
    Convert a string into a list of lines. Replace continuation
    characters. Strip white space, left and right. Drop empty lines.
    '''
    cl = []
    l = s.split('\n')
    cum = []
    for p in l:
        p = p.strip()
        if p.endswith('\\'):
            p = p.rstrip('\\')
            cum.append(p)
        else:
            cum.append(p)
            cl.append(''.join(cum).strip())
            cum = []
    if cum: # in case s ends with backslash
        cl.append(''.join(cum))
    return [x for x in cl if x]

#
# object sets (enables operations on sets of elements)
#
def mkset_obj(*args):
    if args and args[0] == "xml":
        obj = lambda: CibObjectSetRaw(*args[1:])
    else:
        obj = lambda: CibObjectSetCli(*args)
    return obj()

class CibObjectSet(object):
    '''
    Edit or display a set of cib objects.
    repr() for objects representation and
    save() used to store objects into internal structures
    are defined in subclasses.
    '''
    def __init__(self, *args):
        self.obj_list = []
    def _open_url(self,src):
        import urllib
        try:
            return urllib.urlopen(src)
        except:
            pass
        if src == "-":
            return sys.stdin
        try:
            return open(src)
        except:
            pass
        common_err("could not open %s" % src)
        return False
    def init_aux_lists(self):
        '''
        Before edit, initialize two auxiliary lists which will
        hold a list of objects to be removed and a list of
        objects which were created. Then, we can create a new
        object list which will match the current state of
        affairs, i.e. the object set after the last edit.
        '''
        self.remove_objs = copy.copy(self.obj_list)
        self.add_objs = []
    def recreate_obj_list(self):
        '''
        Recreate obj_list: remove deleted objects and add
        created objects
        '''
        for obj in self.remove_objs:
            self.obj_list.remove(obj)
        self.obj_list += self.add_objs
        rmlist = []
        for obj in self.obj_list:
            if obj.invalid:
                rmlist.append(obj)
        for obj in rmlist:
            self.obj_list.remove(obj)
    def edit_save(self,s,erase = False):
        '''
        Save string s to a tmp file. Invoke editor to edit it.
        Parse/save the resulting file. In case of syntax error,
        allow user to reedit. If erase is True, erase the CIB
        first.
        If no changes are done, return silently.
        '''
        tmp = str2tmp(s)
        if not tmp:
            return False
        filehash = hash(s)
        rc = False
        while True:
            if edit_file(tmp) != 0:
                break
            try: f = open(tmp,'r')
            except IOError, msg:
                common_err(msg)
                break
            s = ''.join(f)
            f.close()
            if hash(s) == filehash: # file unchanged
                rc = True
                break
            if erase:
                cib_factory.erase()
            if not self.save(s):
                if ask("Do you want to edit again?"):
                    continue
            rc = True
            break
        try: os.unlink(tmp)
        except: pass
        return rc
    def edit(self):
        if options.batch:
            common_info("edit not allowed in batch mode")
            return False
        cli_display.set_no_pretty()
        s = self.repr()
        cli_display.reset_no_pretty()
        return self.edit_save(s)
    def save_to_file(self,fname):
        if fname == "-":
            f = sys.stdout
        else:
            if not options.batch and os.access(fname,os.F_OK):
                if not ask("File %s exists. Do you want to overwrite it?"%fname):
                    return False
            try: f = open(fname,"w")
            except IOError, msg:
                common_err(msg)
                return False
        rc = True
        cli_display.set_no_pretty()
        s = self.repr()
        cli_display.reset_no_pretty()
        if s:
            f.write(s)
            f.write('\n')
        elif self.obj_list:
            rc = False
        if f != sys.stdout:
            f.close()
        return rc
    def show(self):
        s = self.repr()
        if not s:
            if self.obj_list: # objects could not be displayed
                return False
            else:
                return True
        page_string(s)
    def import_file(self,method,fname):
        if not cib_factory.is_cib_sane():
            return False
        if method == "replace":
            if options.interactive and cib_factory.has_cib_changed():
                if not ask("This operation will erase all changes. Do you want to proceed?"):
                    return False
            cib_factory.erase()
        f = self._open_url(fname)
        if not f:
            return False
        s = ''.join(f)
        if f != sys.stdin:
            f.close()
        return self.save(s)
    def repr(self):
        '''
        Return a string with objects's representations (either
        CLI or XML).
        '''
        return ''
    def save(self,s):
        '''
        For each object:
            - try to find a corresponding object in obj_list
            - if not found: create new
            - if found: replace the object in the obj_list with
              the new object
        See below for specific implementations.
        '''
        pass
    def verify2(self):
        '''
        Test objects for sanity. This is about semantics.
        '''
        rc = 0
        for obj in self.obj_list:
            rc |= obj.check_sanity()
        return rc
    def lookup_cli(self,cli_list):
        for obj in self.obj_list:
            if obj.matchcli(cli_list):
                return obj
    def lookup(self,xml_obj_type,obj_id):
        for obj in self.obj_list:
            if obj.match(xml_obj_type,obj_id):
                return obj
    def drop_remaining(self):
        'Any remaining objects in obj_list are deleted.'
        l = [x.obj_id for x in self.remove_objs]
        return cib_factory.delete(*l)

class CibObjectSetCli(CibObjectSet):
    '''
    Edit or display a set of cib objects (using cli notation).
    '''
    def __init__(self, *args):
        CibObjectSet.__init__(self, *args)
        self.obj_list = cib_factory.mkobj_list("cli",*args)
    def repr(self):
        "Return a string containing cli format of all objects."
        if not self.obj_list:
            return ''
        return '\n'.join(obj.repr_cli() \
            for obj in processing_sort_cli(self.obj_list))
    def process(self,cli_list):
        '''
        Create new objects or update existing ones.
        '''
        comments = get_comments(cli_list)
        obj = self.lookup_cli(cli_list)
        if obj:
            rc = obj.update_from_cli(cli_list) != False
            self.remove_objs.remove(obj)
        else:
            obj = cib_factory.create_from_cli(cli_list)
            rc = obj != None
            if rc:
                self.add_objs.append(obj)
        if rc:
            obj.set_comment(comments)
        return rc
    def save(self,s):
        '''
        Save a user supplied cli format configuration.
        On errors user is typically asked to review the
        configuration (for instance on editting).

        On syntax error (return code 1), no changes are done, but
        on semantic errors (return code 2), some changes did take
        place so object list must be updated properly.

        Finally, once syntax check passed, there's no way back,
        all changes are applied to the current configuration.

        TODO: Implement undo configuration changes.
        '''
        l = []
        rc = True
        err_buf.start_tmp_lineno()
        cp = CliParser()
        for cli_text in lines2cli(s):
            err_buf.incr_lineno()
            cli_list = cp.parse(cli_text)
            if cli_list:
                l.append(cli_list)
            elif cli_list == False:
                rc = False
        err_buf.stop_tmp_lineno()
        # we can't proceed if there was a syntax error, but we
        # can ask the user to fix problems
        if not rc:
            return rc
        self.init_aux_lists()
        if l:
            for cli_list in processing_sort_cli(l):
                if self.process(cli_list) == False:
                    rc = False
        if not self.drop_remaining():
            # this is tricky, we don't know what was removed!
            # it could happen that the user dropped a resource
            # which was running and therefore couldn't be removed
            rc = False
        self.recreate_obj_list()
        return rc

cib_verify = "crm_verify -V -p"
class CibObjectSetRaw(CibObjectSet):
    '''
    Edit or display one or more CIB objects (XML).
    '''
    def __init__(self, *args):
        CibObjectSet.__init__(self, *args)
        self.obj_list = cib_factory.mkobj_list("xml",*args)
    def repr(self):
        "Return a string containing xml of all objects."
        doc = cib_factory.objlist2doc(self.obj_list)
        s = doc.toprettyxml(user_prefs.xmlindent)
        doc.unlink()
        return s
    def repr_configure(self):
        '''
        Return a string containing xml of configure and its
        children.
        '''
        doc = cib_factory.objlist2doc(self.obj_list)
        conf_node = doc.getElementsByTagName("configuration")[0]
        s = conf_node.toprettyxml(user_prefs.xmlindent)
        doc.unlink()
        return s
    def process(self,node):
        if not cib_factory.is_cib_sane():
            return False
        obj = self.lookup(node.tagName,node.getAttribute("id"))
        if obj:
            rc = obj.update_from_node(node) != False
            self.remove_objs.remove(obj)
        else:
            new_obj = cib_factory.create_from_node(node)
            rc = new_obj != None
            if rc:
                self.add_objs.append(new_obj)
        return rc
    def save(self,s):
        try:
            doc = xml.dom.minidom.parseString(s)
        except xml.parsers.expat.ExpatError,msg:
            cib_parse_err(msg)
            return False
        rc = True
        sanitize_cib(doc)
        show_unrecognized_elems(doc)
        newnodes = get_interesting_nodes(doc,[])
        self.init_aux_lists()
        if newnodes:
            for node in processing_sort(newnodes):
                if not self.process(node):
                    rc = False
        if not self.drop_remaining():
            rc = False
        doc.unlink()
        self.recreate_obj_list()
        return rc
    def verify(self):
        if not self.obj_list:
            return True
        cli_display.set_no_pretty()
        rc = pipe_string(cib_verify,self.repr())
        cli_display.reset_no_pretty()
        return rc in (0,1)
    def ptest(self, nograph, scores, verbosity):
        if not cib_factory.is_cib_sane():
            return False
        ptest = "ptest -X -%s" % verbosity.upper()
        if scores:
            ptest = "%s -s" % ptest
        if user_prefs.dotty and not nograph:
            fd,tmpfile = mkstemp()
            ptest = "%s -D %s" % (ptest,tmpfile)
        else:
            tmpfile = None
        doc = cib_factory.objlist2doc(self.obj_list)
        cib = doc.childNodes[0]
        status = cib_status.get_status()
        if not status:
            common_err("no status section found")
            return False
        cib.appendChild(doc.importNode(status,1))
        pipe_string(ptest,doc.toprettyxml())
        doc.unlink()
        if tmpfile:
            p = subprocess.Popen("%s %s" % (user_prefs.dotty,tmpfile), shell=True, bufsize=0, stdin=None, stdout=None, stderr=None, close_fds=True)
            common_info("starting %s to show transition graph"%user_prefs.dotty)
            vars.tmpfiles.append(tmpfile)
        else:
            if not nograph:
                common_info("install graphviz to see a transition graph")
        return True

#
# XML generate utilities
#
hints_list = {
    "instance_attributes": "instance_attributes",
    "meta_attributes": "meta_attributes",
    "operations": "ops",
    "rule": "rule",
    "expression": "expression",
}

def set_id(node,oldnode,id_hint,id_required = True):
    '''
    Set the id attribute for the node.
    Procedure:
    - if the node already contains "id", keep it
    - if the old node contains "id", copy that
    - if neither is true, then create a new one using id_hint
      (exception: if not id_required, then no new id is generated)
    Finally, save the new id in id_store.
    '''
    old_id = None
    new_id = node.getAttribute("id")
    if oldnode and oldnode.getAttribute("id"):
        old_id = oldnode.getAttribute("id")
    if not new_id:
        new_id = old_id
    if not new_id:
        if id_required:
            new_id = id_store.new(node,id_hint)
    else:
        id_store.save(new_id)
    if new_id:
        node.setAttribute("id",new_id)
        if oldnode and old_id == new_id:
            set_id_used_attr(oldnode)

def mkxmlsimple(e,oldnode,id_hint):
    '''
    Create an xml node from the (name,dict) pair. The name is the
    name of the element. The dict contains a set of attributes.
    '''
    node = cib_factory.createElement(e[0])
    for n,v in e[1]:
        if n == "$children": # this one's skipped
            continue
        if n == "operation":
            v = v.lower()
        if n.startswith('$'):
            n = n.lstrip('$')
        if (type(v) != type('') and type(v) != type(u'')) \
                or v: # skip empty strings
            node.setAttribute(n,v)
    id_ref = node.getAttribute("id-ref")
    if id_ref:
        id_ref_2 = cib_factory.resolve_id_ref(e[0],id_ref)
        node.setAttribute("id-ref",id_ref_2)
    else:
        set_id(node,lookup_node(node,oldnode),id_hint)
    return node

def find_operation(rsc_node,name,interval):
    op_node_l = rsc_node.getElementsByTagName("operations")
    for ops in op_node_l:
        for c in ops.childNodes:
            if not is_element(c):
                continue
            if c.tagName != "op":
                continue
            if c.getAttribute("name") == name \
                    and c.getAttribute("interval") == interval:
                return c
def mkxmlnvpairs(e,oldnode,id_hint):
    '''
    Create xml from the (name,dict) pair. The name is the name of
    the element. The dict contains a set of nvpairs. Stuff such
    as instance_attributes.
    NB: Other tags not containing nvpairs are fine if the dict is empty.
    '''
    node = cib_factory.createElement(e[0])
    match_node = lookup_node(node,oldnode)
    #if match_node:
        #print "found nvpairs set:",match_node.tagName,match_node.getAttribute("id")
    id_ref = find_value(e[1],"$id-ref")
    if id_ref:
        id_ref_2 = cib_factory.resolve_id_ref(e[0],id_ref)
        node.setAttribute("id-ref",id_ref_2)
        if e[0] != "operations":
            return node # id_ref is the only attribute (if not operations)
        e[1].remove(["$id-ref",id_ref])
    v = find_value(e[1],"$id")
    if v:
        node.setAttribute("id",v)
        e[1].remove(["$id",v])
    else:
        if e[0] == "operations": # operations don't need no id
            set_id(node,match_node,id_hint,id_required = False)
        else:
            set_id(node,match_node,id_hint)
    try:
        hint = hints_list[e[0]]
    except: hint = ''
    hint = hint and "%s_%s" % (id_hint,hint) or id_hint
    nvpair_pfx = node.getAttribute("id") or hint
    for n,v in e[1]:
        nvpair = cib_factory.createElement("nvpair")
        node.appendChild(nvpair)
        nvpair.setAttribute("name",n)
        if v != None:
            nvpair.setAttribute("value",v)
        set_id(nvpair,lookup_node(nvpair,match_node),nvpair_pfx)
    return node

def mkxmlop(e,oldnode,id_hint):
    '''
    Create an operation xml from the (name,dict) pair.
    '''
    node = cib_factory.createElement(e[0])
    inst_attr = []
    for n,v in e[1]:
        if n in vars.req_op_attributes + vars.op_attributes:
            node.setAttribute(n,v)
        else:
            inst_attr.append([n,v])
    tmp = cib_factory.createElement("operations")
    oldops = lookup_node(tmp,oldnode) # first find old operations
    oldop = lookup_node(node,oldops)
    set_id(node,oldop,id_hint)
    if inst_attr:
        e = ["instance_attributes",inst_attr]
        nia = mkxmlnvpairs(e,oldop,node.getAttribute("id"))
        node.appendChild(nia)
    return node

def mkxmldate(e,oldnode,id_hint):
    '''
    Create a date_expression xml from the (name,dict) pair.
    '''
    node = cib_factory.createElement(e[0])
    operation = find_value(e[1],"operation").lower()
    node.setAttribute("operation", operation)
    old_date = lookup_node(node,oldnode) # first find old date element
    set_id(node,old_date,id_hint)
    date_spec_attr = []
    for n,v in e[1]:
        if n in vars.date_ops or n == "operation":
            continue
        elif n in vars.in_range_attrs:
            node.setAttribute(n,v)
        else:
            date_spec_attr.append([n,v])
    if not date_spec_attr:
        return node
    elem = operation == "date_spec" and "date_spec" or "duration"
    tmp = cib_factory.createElement(elem)
    old_date_spec = lookup_node(tmp,old_date) # first find old date element
    set_id(tmp,old_date_spec,id_hint)
    for n,v in date_spec_attr:
        tmp.setAttribute(n,v)
    node.appendChild(tmp)
    return node

def mkxmlrsc_set(e,oldnode,id_hint):
    '''
    Create a resource_set xml from the (name,dict) pair.
    '''
    node = cib_factory.createElement(e[0])
    old_rsc_set = lookup_node(node,oldnode) # first find old date element
    set_id(node,old_rsc_set,id_hint)
    for ref in e[1]:
        if ref[0] == "resource_ref":
            ref_node = cib_factory.createElement(ref[0])
            ref_node.setAttribute(ref[1][0],ref[1][1])
            node.appendChild(ref_node)
        elif ref[0] in ("sequential", "action", "role"):
            node.setAttribute(ref[0], ref[1])
    return node

conv_list = {
    "params": "instance_attributes",
    "meta": "meta_attributes",
    "property": "cluster_property_set",
    "rsc_defaults": "meta_attributes",
    "op_defaults": "meta_attributes",
    "attributes": "instance_attributes",
    "operations": "operations",
    "op": "op",
}
def mkxmlnode(e,oldnode,id_hint):
    '''
    Create xml from the (name,dict) pair. The name is the name of
    the element. The dict contains either a set of nvpairs or a
    set of attributes. The id is either generated or copied if
    found in the provided xml. Stuff such as instance_attributes.
    '''
    if e[0] in conv_list:
        e[0] = conv_list[e[0]]
    if e[0] in ("instance_attributes","meta_attributes","operations","cluster_property_set"):
        return mkxmlnvpairs(e,oldnode,id_hint)
    elif e[0] == "op":
        return mkxmlop(e,oldnode,id_hint)
    elif e[0] == "date_expression":
        return mkxmldate(e,oldnode,id_hint)
    elif e[0] == "resource_set":
        return mkxmlrsc_set(e,oldnode,id_hint)
    else:
        return mkxmlsimple(e,oldnode,id_hint)

def new_cib():
    doc = xml.dom.minidom.Document()
    cib = doc.createElement("cib")
    doc.appendChild(cib)
    configuration = doc.createElement("configuration")
    cib.appendChild(configuration)
    crm_config = doc.createElement("crm_config")
    configuration.appendChild(crm_config)
    rsc_defaults = doc.createElement("rsc_defaults")
    configuration.appendChild(rsc_defaults)
    op_defaults = doc.createElement("op_defaults")
    configuration.appendChild(op_defaults)
    nodes = doc.createElement("nodes")
    configuration.appendChild(nodes)
    resources = doc.createElement("resources")
    configuration.appendChild(resources)
    constraints = doc.createElement("constraints")
    configuration.appendChild(constraints)
    return doc,cib,crm_config,rsc_defaults,op_defaults,nodes,resources,constraints
def mk_topnode(doc, tag):
    "Get configuration element or create/append if there's none."
    try:
        e = doc.getElementsByTagName(tag)[0]
    except:
        e = doc.createElement(tag)
        conf = doc.getElementsByTagName("configuration")[0]
        if conf:
            conf.appendChild(e)
        else:
            return None
    return e

def set_nvpair(set_node,name,value):
    n_id = set_node.getAttribute("id")
    for c in set_node.childNodes:
        if is_element(c) and c.getAttribute("name") == name:
            c.setAttribute("value",value)
            return
    np = cib_factory.createElement("nvpair")
    np.setAttribute("name",name)
    np.setAttribute("value",value)
    new_id = id_store.new(np,n_id)
    np.setAttribute("id",new_id)
    set_node.appendChild(np)

def xml_cmp(n, m, show = False):
    rc = hash(n.toxml()) == hash(m.toxml())
    if not rc and show and user_prefs.get_debug():
        print "original:",n.toprettyxml()
        print "processed:",m.toprettyxml()
    return hash(n.toxml()) == hash(m.toxml())

#
# CLI format generation utilities (from XML)
#
def cli_format(pl,format):
    if format > 0:
        return ' \\\n\t'.join(pl)
    else:
        return ' '.join(pl)
def nvpair_format(n,v):
    return v == None and cli_display.attr_name(n) \
        or '%s="%s"'%(cli_display.attr_name(n),cli_display.attr_value(v))
def cli_pairs(pl):
    'Return a string of name="value" pairs (passed in a list of pairs).'
    l = []
    for n,v in pl:
        l.append(nvpair_format(n,v))
    return ' '.join(l)

def op2list(node):
    pl = []
    action = ""
    for name in node.attributes.keys():
        if name == "name":
            action = node.getAttribute(name)
        elif name != "id": # skip the id
            pl.append([name,node.getAttribute(name)])
    if not action:
        common_err("op is invalid (no name)")
    return action,pl
def op_instattr(node):
    pl = []
    for c in node.childNodes:
        if not is_element(c):
            continue
        if c.tagName != "instance_attributes":
            common_err("only instance_attributes are supported in operations")
        else:
            pl += nvpairs2list(c)
    return pl
def cli_op(node):
    action,pl = op2list(node)
    if not action:
        return ""
    pl += op_instattr(node)
    return "%s %s %s" % (cli_display.keyword("op"),action,cli_pairs(pl))
def cli_operations(node,format = 1):
    l = []
    node_id = node.getAttribute("id")
    s = ''
    if node_id:
        s = '$id="%s"' % node_id
    idref = node.getAttribute("id-ref")
    if idref:
        s = '%s $id-ref="%s"' % (s,idref)
    if s:
        l.append("%s %s" % (cli_display.keyword("operations"),s))
    for c in node.childNodes:
        if is_element(c) and c.tagName == "op":
            l.append(cli_op(c))
    return cli_format(l,format)
def date_exp2cli(node):
    l = []
    operation = node.getAttribute("operation")
    l.append(cli_display.keyword("date"))
    l.append(cli_display.keyword(operation))
    if operation in vars.simple_date_ops:
        value = node.getAttribute(operation == 'lt' and "end" or "start")
        l.append('"%s"' % cli_display.attr_value(value))
    else:
        if operation == 'in_range':
            for name in vars.in_range_attrs:
                v = node.getAttribute(name)
                if v:
                    l.append(nvpair_format(name,v))
        for c in node.childNodes:
            if is_element(c) and c.tagName in ("duration","date_spec"):
                pl = []
                for name in c.attributes.keys():
                    if name != "id":
                        pl.append([name,c.getAttribute(name)])
                l.append(cli_pairs(pl))
    return ' '.join(l)
def binary_op_format(op):
    l = op.split(':')
    if len(l) == 2:
        return "%s:%s" % (l[0], cli_display.keyword(l[1]))
    else:
        return cli_display.keyword(op)
def exp2cli(node):
    operation = node.getAttribute("operation")
    type = node.getAttribute("type")
    if type:
        operation = "%s:%s" % (type, operation)
    attribute = node.getAttribute("attribute")
    value = node.getAttribute("value")
    if not value:
        return "%s %s" % (binary_op_format(operation),attribute)
    else:
        return "%s %s %s" % (attribute,binary_op_format(operation),value)
def get_score(node):
    score = node.getAttribute("score")
    if not score:
        score = node.getAttribute("score-attribute")
    else:
        if score.find("INFINITY") >= 0:
            score = score.replace("INFINITY","inf")
    return score + ":"
def cli_rule(node):
    s = []
    node_id = node.getAttribute("id")
    if node_id:
        s.append('$id="%s"' % node_id)
    else:
        idref = node.getAttribute("id-ref")
        if idref:
            return '$id-ref="%s"' % idref
    rsc_role = node.getAttribute("role")
    if rsc_role:
        s.append('$role="%s"' % rsc_role)
    s.append(cli_display.score(get_score(node)))
    bool_op = node.getAttribute("boolean-op")
    if not bool_op:
        bool_op = "and"
    exp = []
    for c in node.childNodes:
        if not is_element(c):
            continue
        if c.tagName == "date_expression":
            exp.append(date_exp2cli(c))
        elif c.tagName == "expression":
            exp.append(exp2cli(c))
    expression = (" %s "%cli_display.keyword(bool_op)).join(exp)
    return "%s %s" % (' '.join(s),expression)
def node_head(node):
    obj_type = vars.cib_cli_map[node.tagName]
    node_id = node.getAttribute("id")
    uname = node.getAttribute("uname")
    s = cli_display.keyword(obj_type)
    if node_id != uname:
        s = '%s $id="%s"' % (s, node_id)
    s = '%s %s' % (s, cli_display.id(uname))
    type = node.getAttribute("type")
    if type != vars.node_default_type:
        s = '%s:%s' % (s, type)
    return s
def cli_add_description(node,l):
    desc = node.getAttribute("description")
    if desc:
        l.append(nvpair_format("description",desc))
def primitive_head(node):
    obj_type = vars.cib_cli_map[node.tagName]
    node_id = node.getAttribute("id")
    ra_type = node.getAttribute("type")
    ra_class = node.getAttribute("class")
    ra_provider = node.getAttribute("provider")
    s1 = s2 = ''
    if ra_class:
        s1 = "%s:"%ra_class
    if ra_provider:
        s2 = "%s:"%ra_provider
    s = cli_display.keyword(obj_type)
    id = cli_display.id(node_id)
    return "%s %s %s" % (s, id, ''.join((s1,s2,ra_type)))

def cont_head(node):
    obj_type = vars.cib_cli_map[node.tagName]
    node_id = node.getAttribute("id")
    children = []
    for c in node.childNodes:
        if not is_element(c):
            continue
        if (obj_type == "group" and is_primitive(c)) or \
                is_child_rsc(c):
            children.append(cli_display.rscref(c.getAttribute("id")))
        elif obj_type in vars.clonems_tags and is_child_rsc(c):
            children.append(cli_display.rscref(c.getAttribute("id")))
    s = cli_display.keyword(obj_type)
    id = cli_display.id(node_id)
    return "%s %s %s" % (s, id, ' '.join(children))
def location_head(node):
    obj_type = vars.cib_cli_map[node.tagName]
    node_id = node.getAttribute("id")
    rsc = cli_display.rscref(node.getAttribute("rsc"))
    s = cli_display.keyword(obj_type)
    id = cli_display.id(node_id)
    s = "%s %s %s"%(s,id,rsc)
    pref_node = node.getAttribute("node")
    score = cli_display.score(get_score(node))
    if pref_node:
        return "%s %s %s" % (s,score,pref_node)
    else:
        return s
def mkrscrole(node,n):
    rsc = cli_display.rscref(node.getAttribute(n))
    rsc_role = node.getAttribute(n + "-role")
    if rsc_role:
        return "%s:%s"%(rsc,rsc_role)
    else:
        return rsc
def mkrscaction(node,n):
    rsc = cli_display.rscref(node.getAttribute(n))
    rsc_action = node.getAttribute(n + "-action")
    if rsc_action:
        return "%s:%s"%(rsc,rsc_action)
    else:
        return rsc
def rsc_set_constraint(node,obj_type):
    col = []
    cnt = 0
    for n in node.getElementsByTagName("resource_set"):
        sequential = True
        if n.getAttribute("sequential") == "false":
            sequential = False
        if not sequential:
            col.append("(")
        role = n.getAttribute("role")
        action = n.getAttribute("action")
        for r in n.getElementsByTagName("resource_ref"):
            rsc = cli_display.rscref(r.getAttribute("id"))
            q = (obj_type == "colocation") and role or action
            col.append(q and "%s:%s"%(rsc,q) or rsc)
            cnt += 1
        if not sequential:
            col.append(")")
    if cnt <= 2: # a degenerate thingie
        col.insert(0,"_rsc_set_")
    return col
def two_rsc_constraint(node,obj_type):
    col = []
    if obj_type == "colocation":
        col.append(mkrscrole(node,"rsc"))
        col.append(mkrscrole(node,"with-rsc"))
    else:
        col.append(mkrscaction(node,"first"))
        col.append(mkrscaction(node,"then"))
    return col
def simple_constraint_head(node):
    obj_type = vars.cib_cli_map[node.tagName]
    node_id = node.getAttribute("id")
    s = cli_display.keyword(obj_type)
    id = cli_display.id(node_id)
    score = cli_display.score(get_score(node))
    if node.getElementsByTagName("resource_set"):
        col = rsc_set_constraint(node,obj_type)
    else:
        col = two_rsc_constraint(node,obj_type)
    symm = node.getAttribute("symmetrical")
    if symm:
        col.append("symmetrical=%s"%symm)
    return "%s %s %s %s" % (s,id,score,' '.join(col))
#
################################################################

#
# cib element classes (CibObject the parent class)
#
class CibObject(object):
    '''
    The top level object of the CIB. Resources and constraints.
    '''
    state_fmt = "%16s %-8s%-8s%-8s%-8s%-8s%-4s"
    def __init__(self,xml_obj_type,obj_id = None):
        if not xml_obj_type in cib_object_map:
            unsupported_err(xml_obj_type)
            return
        self.obj_type = cib_object_map[xml_obj_type][0]
        self.parent_type = cib_object_map[xml_obj_type][2]
        self.xml_obj_type = xml_obj_type
        self.origin = "" # where did it originally come from?
        self.nocli = False # we don't support this one
        self.updated = False # was the object updated
        self.invalid = False # the object has been invalidated (removed)
        self.moved = False # the object has been moved (from/to a container)
        self.recreate = False # constraints to be recreated
        self.comment = '' # comment as text
        self.parent = None # object superior (group/clone/ms)
        self.children = [] # objects inferior
        if obj_id:
            if not self.mknode(obj_id):
                self = None # won't do :(
        else:
            self.obj_id = None
            self.node = None
    def dump_state(self):
        'Print object status'
        print self.state_fmt % \
            (self.obj_id,self.origin,self.updated,self.moved,self.invalid, \
            self.parent and self.parent.obj_id or "", \
            len(self.children))
    def repr_cli(self,node = None,format = 1):
        '''
        CLI representation for the node. Defined in subclasses.
        '''
        return ''
    def cli2node(self,cli,oldnode = None):
        '''
        Convert CLI representation to a DOM node.
        Defined in subclasses.
        '''
        return None
    def cli_format(self,l,format):
        '''
        Format and add comment (if any).
        '''
        s =  cli_format(l,format)
        return (self.comment and format >=0) and '\n'.join([self.comment,s]) or s
    def set_comment(self,l):
        s = '\n'.join(l)
        if self.comment != s:
            self.comment = s
            self.modified = True
    def pull_comments(self):
        '''
        Collect comments from within this node.  Remove them from
        the parent and stuff them in self.comments as an array.
        '''
        l = []
        cnodes = [x for x in self.node.childNodes if is_comment(x)]
        for n in cnodes:
            l.append(n.data)
            n.parentNode.removeChild(n)
        # convert comments from XML node to text. Multiple comments
        # are concatenated with '\n'.
        if not l:
            self.comment = ''
            return
        s = '\n'.join(l)
        l = s.split('\n')
        for i in range(len(l)):
            if not l[i].startswith('#'):
                l[i] = '#%s' % l[i]
        self.comment = '\n'.join(l)
    def save_xml(self,node):
        self.obj_id = node.getAttribute("id")
        self.node = node
    def mknode(self,obj_id):
        if not cib_factory.is_cib_sane():
            return False
        if id_in_use(obj_id):
            return False
        if self.xml_obj_type in vars.defaults_tags:
            tag = "meta_attributes"
        else:
            tag = self.xml_obj_type
        self.node = cib_factory.createElement(tag)
        self.obj_id = obj_id
        self.node.setAttribute("id",self.obj_id)
        self.origin = "user"
        return True
    def mkcopy(self):
        '''
        Create a new object with the same obj_id and obj_type
        (for the purpose of CibFactory.delete_objects)
        '''
        obj_copy = CibObject(self.xml_obj_type)
        obj_copy.obj_id = self.obj_id
        obj_copy.obj_type = self.obj_type
        return obj_copy
    def can_be_renamed(self):
        '''
        Return False if this object can't be renamed.
        '''
        if is_rsc_running(self.obj_id):
            common_err("cannot rename a running resource (%s)" % self.obj_id)
            return False
        if not is_live_cib() and self.node.tagName == "node":
            common_err("cannot rename nodes")
            return False
        return True
    def attr_exists(self,attr):
        if not attr in self.node.attributes.keys():
            no_attribute_err(attr,self.obj_id)
            return False
        return True
    def cli_use_validate(self):
        '''
        Check validity of the object, as we know it. It may
        happen that we don't recognize a construct, but that the
        object is still valid for the CRM. In that case, the
        object is marked as "CLI read only", i.e. we will neither
        convert it to CLI nor try to edit it in that format.

        The validation procedure:
        we convert xml to cli and then back to xml. If the two
        xml representations match then we can understand the xml.
        '''
        if not self.node:
            return True
        if not self.attr_exists("id"):
            return False
        cli_display.set_no_pretty()
        cli_text = self.repr_cli(format = -1)
        cli_display.reset_no_pretty()
        if not cli_text:
            return False
        xml2 = self.cli2node(cli_text)
        if not xml2:
            return False
        rc = xml_cmp(self.node, xml2, show = True)
        xml2.unlink()
        return rc
    def check_sanity(self):
        '''
        Right now, this is only for primitives.
        '''
        return 0
    def matchcli(self,cli_list):
        head = cli_list[0]
        return self.obj_type == head[0] \
            and self.obj_id == find_value(head[1],"id")
    def match(self,xml_obj_type,obj_id):
        return self.xml_obj_type == xml_obj_type and self.obj_id == obj_id
    def obj_string(self):
        return "%s:%s" % (self.obj_type,self.obj_id)
    def reset_updated(self):
        self.updated = False
        self.moved = False
        self.recreate = False
        for child in self.children:
            child.reset_updated()
    def propagate_updated(self):
        if self.parent:
            self.parent.updated = self.updated
            self.parent.propagate_updated()
    def update_links(self):
        '''
        Update the structure links for the object (self.children,
        self.parent). Update also the dom nodes, if necessary.
        '''
        self.children = []
        if self.obj_type not in vars.container_tags:
            return
        for c in self.node.childNodes:
            if is_child_rsc(c):
                child = cib_factory.find_object_for_node(c)
                if not child:
                    missing_obj_err(c)
                    continue
                child.parent = self
                self.children.append(child)
                if not c.isSameNode(child.node):
                    rmnode(child.node)
                    child.node = c
    def update_from_cli(self,cli_list):
        'Update ourselves from the cli intermediate.'
        if not cib_factory.is_cib_sane():
            return False
        if not cib_factory.verify_cli(cli_list):
            return False
        oldnode = self.node
        id_store.remove_xml(oldnode)
        newnode = self.cli2node(cli_list)
        if not newnode:
            id_store.store_xml(oldnode)
            return False
        if xml_cmp(oldnode,newnode):
            newnode.unlink()
            return True # the new and the old versions are equal
        self.node = newnode
        if user_prefs.is_check_always() \
                and self.check_sanity() > 1:
            id_store.remove_xml(newnode)
            id_store.store_xml(oldnode)
            self.node = oldnode
            newnode.unlink()
            return False
        oldnode.parentNode.replaceChild(newnode,oldnode)
        cib_factory.adjust_children(self,cli_list)
        oldnode.unlink()
        self.updated = True
        self.propagate_updated()
        return True
    def update_from_node(self,node):
        'Update ourselves from a doc node.'
        if not node:
            return False
        if not cib_factory.is_cib_sane():
            return False
        oldxml = self.node
        newxml = node
        if xml_cmp(oldxml,newxml):
            return True # the new and the old versions are equal
        if not id_store.replace_xml(oldxml,newxml):
            return False
        oldxml.unlink()
        self.node = cib_factory.doc.importNode(newxml,1)
        cib_factory.topnode[self.parent_type].appendChild(self.node)
        self.update_links()
        self.updated = True
        self.propagate_updated()
    def top_parent(self):
        '''Return the top parent or self'''
        if self.parent:
            return self.parent.top_parent()
        else:
            return self
    def find_child_in_node(self,child):
        for c in self.node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == child.obj_type and \
                    c.getAttribute("id") == child.obj_id:
                return c
        return None
    def filter(self,*args):
        "Filter objects."
        if not args:
            return True
        if args[0] == "NOOBJ":
            return False
        if args[0] == "changed":
            return self.updated or self.origin == "user"
        return self.obj_id in args

def mk_cli_list(cli):
    'Sometimes we get a string and sometimes a list.'
    if type(cli) == type('') or type(cli) == type(u''):
        return CliParser().parse(cli)
    else:
        return cli

class CibNode(CibObject):
    '''
    Node and node's attributes.
    '''
    def repr_cli(self,node = None,format = 1):
        '''
        We assume that uname is unique.
        '''
        if not node:
            node = self.node
        l = []
        l.append(node_head(node))
        cli_add_description(node,l)
        for c in node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "instance_attributes":
                l.append("%s %s" % \
                    (cli_display.keyword("attributes"), \
                    cli_pairs(nvpairs2list(c))))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = self.node
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        obj_id = find_value(head[1],"$id")
        if not obj_id:
            obj_id = find_value(head[1],"uname")
        if not obj_id:
            return None
        type = find_value(head[1],"type")
        if not type:
            type = vars.node_default_type
            head[1].append(["type",type])
        headnode = mkxmlsimple(head,cib_factory.topnode[cib_object_map[self.xml_obj_type][2]],'node')
        id_hint = headnode.getAttribute("id")
        for e in cli_list[1:]:
            n = mkxmlnode(e,oldnode,id_hint)
            headnode.appendChild(n)
        remove_id_used_attributes(cib_factory.topnode[cib_object_map[self.xml_obj_type][2]])
        return headnode

class CibPrimitive(CibObject):
    '''
    Primitives.
    '''
    def repr_cli(self,node = None,format = 1):
        if not node:
            node = self.node
        l = []
        l.append(primitive_head(node))
        cli_add_description(node,l)
        for c in node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "instance_attributes":
                l.append("%s %s" % \
                    (cli_display.keyword("params"), \
                    cli_pairs(nvpairs2list(c))))
            elif c.tagName == "meta_attributes":
                l.append("%s %s" % \
                    (cli_display.keyword("meta"), \
                    cli_pairs(nvpairs2list(c))))
            elif c.tagName == "operations":
                l.append(cli_operations(c,format))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        '''
        Convert a CLI description to DOM node.
        Try to preserve as many ids as possible in case there's
        an old XML version.
        '''
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = self.node
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        headnode = mkxmlsimple(head,oldnode,'rsc')
        id_hint = headnode.getAttribute("id")
        operations = None
        for e in cli_list[1:]:
            n = mkxmlnode(e,oldnode,id_hint)
            if keyword_cmp(e[0], "operations"):
                operations = n
            if not keyword_cmp(e[0], "op"):
                headnode.appendChild(n)
            else:
                if not operations:
                    operations = mkxmlnode(["operations",{}],oldnode,id_hint)
                    headnode.appendChild(operations)
                operations.appendChild(n)
        remove_id_used_attributes(oldnode)
        return headnode
    def check_sanity(self):
        '''
        Check operation timeouts and if all required parameters
        are defined.
        '''
        if not self.node:  # eh?
            common_err("%s: no xml (strange)" % self.obj_id)
            return user_prefs.get_check_rc()
        from ra import RAInfo
        ra_type = self.node.getAttribute("type")
        ra_class = self.node.getAttribute("class")
        ra_provider = self.node.getAttribute("provider")
        ra = RAInfo(ra_class,ra_type,ra_provider)
        if not ra.mk_ra_node():  # no RA found?
            ra.error("no such resource agent")
            return user_prefs.get_check_rc()
        params = []
        for c in self.node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "instance_attributes":
                params += nvpairs2list(c)
        rc1 = ra.sanity_check_params(self.obj_id, params)
        actions = {}
        for c in self.node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "operations":
                for c2 in c.childNodes:
                    if is_element(c2) and c2.tagName == "op":
                        op,pl = op2list(c2)
                        if op:
                            actions[op] = pl
        rc2 = ra.sanity_check_ops(self.obj_id, actions)
        return rc1 | rc2

class CibContainer(CibObject):
    '''
    Groups and clones and ms.
    '''
    def repr_cli(self,node = None,format = 1):
        if not node:
            node = self.node
        l = []
        l.append(cont_head(node))
        cli_add_description(node,l)
        for c in node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "instance_attributes":
                l.append("%s %s" % \
                    (cli_display.keyword("params"), \
                    cli_pairs(nvpairs2list(c))))
            elif c.tagName == "meta_attributes":
                l.append("%s %s" % \
                    (cli_display.keyword("meta"), \
                    cli_pairs(nvpairs2list(c))))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = self.node
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        headnode = mkxmlsimple(head,oldnode,'grp')
        id_hint = headnode.getAttribute("id")
        for e in cli_list[1:]:
            n = mkxmlnode(e,oldnode,id_hint)
            headnode.appendChild(n)
        v = find_value(head[1],"$children")
        if v:
            for child_id in v:
                obj = cib_factory.find_object(child_id)
                if obj:
                    n = obj.node.cloneNode(1)
                    headnode.appendChild(n)
                else:
                    no_object_err(child_id)
        remove_id_used_attributes(oldnode)
        return headnode

class CibLocation(CibObject):
    '''
    Location constraint.
    '''
    def repr_cli(self,node = None,format = 1):
        if not node:
            node = self.node
        l = []
        l.append(location_head(node))
        for c in node.childNodes:
            if not is_element(c):
                continue
            if c.tagName == "rule":
                l.append("%s %s" % \
                    (cli_display.keyword("rule"), cli_rule(c)))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = self.node
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        headnode = mkxmlsimple(head,oldnode,'location')
        id_hint = headnode.getAttribute("id")
        oldrule = None
        for e in cli_list[1:]:
            if e[0] in ("expression","date_expression"):
                n = mkxmlnode(e,oldrule,id_hint)
            else:
                n = mkxmlnode(e,oldnode,id_hint)
            if keyword_cmp(e[0], "rule"):
                add_missing_attr(n)
                rule = n
                headnode.appendChild(n)
                oldrule = lookup_node(rule,oldnode,location_only=True)
            else:
                rule.appendChild(n)
        remove_id_used_attributes(oldnode)
        return headnode

class CibSimpleConstraint(CibObject):
    '''
    Colocation and order constraints.
    '''
    def repr_cli(self,node = None,format = 1):
        if not node:
            node = self.node
        l = []
        l.append(simple_constraint_head(node))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = self.node
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        headnode = mkxmlsimple(head,oldnode,'')
        id_hint = headnode.getAttribute("id")
        for e in cli_list[1:]:
            # if more than one element, it's a resource set
            n = mkxmlnode(e,oldnode,id_hint)
            headnode.appendChild(n)
        remove_id_used_attributes(oldnode)
        return headnode

class CibProperty(CibObject):
    '''
    Cluster properties.
    '''
    def repr_cli(self,node = None,format = 1):
        if not node:
            node = self.node
        l = []
        l.append(cli_display.keyword(self.obj_type))
        properties = nvpairs2list(node, add_id = True)
        for n,v in properties:
            if n == "$id":
                l[0] = '%s %s="%s"' % (l[0],n,v)
            else:
                l.append(nvpair_format(n,v))
        return self.cli_format(l,format)
    def cli2node(self,cli,oldnode = None):
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not oldnode:
            oldnode = cib_factory.topnode[cib_object_map[self.xml_obj_type][2]]
        head = copy.copy(cli_list[0])
        head[0] = backtrans[head[0]]
        obj_id = find_value(head[1],"$id")
        if not obj_id:
            obj_id = cib_object_map[self.xml_obj_type][3]
        headnode = mkxmlnode(head,oldnode,obj_id)
        remove_id_used_attributes(oldnode)
        return headnode
    def matchcli(self,cli_list):
        head = cli_list[0]
        return self.obj_type == head[0] \
            and self.obj_id == find_value(head[1],"$id")
#
################################################################

#
# cib update interface (cibadmin)
#
cib_piped = "cibadmin -p"
def cib_delete_element(obj):
    'Remove one element from the CIB.'
    if obj.xml_obj_type in vars.defaults_tags:
        node = cib_factory.createElement("meta_attributes")
    else:
        node = cib_factory.createElement(obj.xml_obj_type)
    node.setAttribute("id",obj.obj_id)
    rc = pipe_string("%s -D" % cib_piped, node.toxml())
    if rc != 0:
        update_err(obj.obj_id,'-D',node.toprettyxml())
    node.unlink()
    return rc
def cib_update_elements(upd_list):
    'Update a set of objects in the CIB.'
    l = [x.obj_id for x in upd_list]
    o = CibObjectSetRaw(*l)
    xml = o.repr_configure()
    rc = pipe_string("%s -U" % cib_piped, xml)
    if rc != 0:
        update_err(' '.join(l),'-U',xml)
    return rc
def cib_replace_element(obj):
    comm_node = None
    if obj.comment:
        comm_node = cib_factory.createComment(s)
        if obj.node.hasChildNodes():
            obj.node.insertBefore(comm_node, obj.node.firstChild)
        else:
            obj.node.appendChild(comm_node)
    rc = pipe_string("%s -R -o %s" % \
        (cib_piped, obj.parent_type), obj.node.toxml())
    if rc != 0:
        update_err(obj.obj_id,'-R',obj.node.toprettyxml())
    if comm_node:
        rmnode(comm_node)
    return rc
def cib_delete_moved_children(obj):
    for c in obj.children:
        if c.origin == "cib" and c.moved:
            cib_delete_element(c)

def get_cib_default(property):
    if cib_factory.is_cib_sane():
        return cib_factory.get_property(property)

# xml -> cli translations (and classes)
cib_object_map = {
    "node": ( "node", CibNode, "nodes" ),
    "primitive": ( "primitive", CibPrimitive, "resources" ),
    "group": ( "group", CibContainer, "resources" ),
    "clone": ( "clone", CibContainer, "resources" ),
    "master": ( "ms", CibContainer, "resources" ),
    "rsc_location": ( "location", CibLocation, "constraints" ),
    "rsc_colocation": ( "colocation", CibSimpleConstraint, "constraints" ),
    "rsc_order": ( "order", CibSimpleConstraint, "constraints" ),
    "cluster_property_set": ( "property", CibProperty, "crm_config", "cib-bootstrap-options" ),
    "rsc_defaults": ( "rsc_defaults", CibProperty, "rsc_defaults", "rsc-options" ),
    "op_defaults": ( "op_defaults", CibProperty, "op_defaults", "op-options" ),
}
backtrans = odict()  # generate a translation cli -> tag
for key in cib_object_map:
    backtrans[cib_object_map[key][0]] = key
cib_topnodes = []  # get a list of parents
for key in cib_object_map:
    if not cib_object_map[key][2] in cib_topnodes:
        cib_topnodes.append(cib_object_map[key][2])

cib_upgrade = "cibadmin --upgrade --force"
class CibFactory(Singleton):
    '''
    Juggle with CIB objects.
    See check_structure below for details on the internal cib
    representation.
    '''
    def __init__(self):
        self.init_vars()
        self.regtest = options.regression_tests
        self.all_committed = True # has commit produced error
        self._no_constraint_rm_msg = False # internal (just not to produce silly messages)
        self.supported_cib_re = "^pacemaker-1[.]0$"
    def is_cib_sane(self):
        if not self.doc:
            empty_cib_err()
            return False
        return True
    #
    # check internal structures
    #
    def check_topnode(self,obj):
        if not obj.node.parentNode.isSameNode(self.topnode[obj.parent_type]):
            common_err("object %s is not linked to %s"%(obj.obj_id,obj.parent_type))
    def check_parent(self,obj,parent):
        if not obj in parent.children:
            common_err("object %s does not reference its child %s"%(parent.obj_id,obj.obj_id))
            return False
        if not parent.node.isSameNode(obj.node.parentNode):
            common_err("object %s node is not a child of its parent %s, but %s:%s"%(obj.obj_id,parent.obj_id,obj.node.tagName,obj.node.getAttribute("id")))
            return False
    def check_structure(self):
        #print "Checking structure..."
        if not self.doc:
            empty_cib_err()
            return False
        rc = True
        for obj in self.cib_objects:
            #print "Checking %s... (%s)" % (obj.obj_id,obj.nocli)
            if obj.parent:
                if self.check_parent(obj,obj.parent) == False:
                    rc = False
            else:
                if self.check_topnode(obj) == False:
                    rc = False
            for child in obj.children:
                if self.check_parent(child,child.parent) == False:
                    rc = False
        return rc
    def regression_testing(self,param):
        # provide some help for regression testing
        # in particular by trying to provide output which is
        # easier to predict
        if param == "off":
            self.regtest = False
        elif param == "on":
            self.regtest = True
        else:
            common_warn("bad parameter for regtest: %s" % param)
    def createElement(self,tag):
        if self.doc:
            return self.doc.createElement(tag)
        else:
            empty_cib_err()
    def createComment(self,s):
        if self.doc:
            return self.doc.createComment(s)
        else:
            empty_cib_err()
    def is_cib_supported(self,cib):
        'Do we support this CIB?'
        req = cib.getAttribute("crm_feature_set")
        validator = cib.getAttribute("validate-with")
        if validator and re.match(self.supported_cib_re,validator):
            return True
        cib_ver_unsupported_err(validator,req)
        return False
    def upgrade_cib_06to10(self,force = False):
        'Upgrade the CIB from 0.6 to 1.0.'
        if not self.doc:
            empty_cib_err()
            return False
        cib = self.doc.getElementsByTagName("cib")
        if not cib:
            common_err("CIB has no cib element")
            return False
        req = cib[0].getAttribute("crm_feature_set")
        validator = cib[0].getAttribute("validate-with")
        if force or not validator or re.match("0[.]6",validator):
            return ext_cmd(cib_upgrade) == 0
    def import_cib(self):
        'Parse the current CIB (from cibadmin -Q).'
        self.doc,cib = read_cib(cibdump2doc)
        if not self.doc:
            return False
        if not cib:
            common_err("CIB has no cib element")
            self.reset()
            return False
        if not self.is_cib_supported(cib):
            self.reset()
            return False
        for attr in cib.attributes.keys():
            self.cib_attrs[attr] = cib.getAttribute(attr)
        for t in cib_topnodes:
            self.topnode[t] = get_conf_elem(self.doc, t)
            if not self.topnode[t]:
                self.topnode[t] = mk_topnode(self.doc, t)
                self.missing_topnodes.append(t)
            if not self.topnode[t]:
                common_err("could not create %s node; out of memory?" % t)
                self.reset()
                return False
        return True
    #
    # create a doc from the list of objects
    # (used by CibObjectSetRaw)
    #
    def regtest_filter(self,cib):
        for attr in ("epoch","admin_epoch"):
            if cib.getAttribute(attr):
                cib.setAttribute(attr,"0")
        for attr in ("cib-last-written",):
            if cib.getAttribute(attr):
                cib.removeAttribute(attr)
    def set_cib_attributes(self,cib):
        for attr in self.cib_attrs:
            cib.setAttribute(attr,self.cib_attrs[attr])
        if self.regtest:
            self.regtest_filter(cib)
    def objlist2doc(self,obj_list,obj_filter = None):
        '''
        Return document containing objects in obj_list.
        Must remove all children from the object list, because
        printing xml of parents will include them.
        Optional filter to sieve objects.
        '''
        doc,cib,crm_config,rsc_defaults,op_defaults,nodes,resources,constraints = new_cib()
        # get only top parents for the objects in the list
        # e.g. if we get a primitive which is part of a clone,
        # then the clone gets in, not the primitive
        # dict will weed out duplicates
        d = {}
        for obj in obj_list:
            if obj_filter and not obj_filter(obj):
                continue
            d[obj.top_parent()] = 1
        for obj in d:
            i_node = doc.importNode(obj.node,1)
            add_comment(doc,i_node,obj.comment)
            if obj.parent_type == "nodes":
                nodes.appendChild(i_node)
            elif obj.parent_type == "resources":
                resources.appendChild(i_node)
            elif obj.parent_type == "constraints":
                constraints.appendChild(i_node)
            elif obj.parent_type == "crm_config":
                crm_config.appendChild(i_node)
            elif obj.parent_type == "rsc_defaults":
                rsc_defaults.appendChild(i_node)
            elif obj.parent_type == "op_defaults":
                op_defaults.appendChild(i_node)
        self.set_cib_attributes(cib)
        return doc
    #
    # commit changed objects to the CIB
    #
    def attr_match(self,c,a):
        'Does attribute match?'
        try: cib_attr = self.cib_attrs[a]
        except: cib_attr = None
        return c.getAttribute(a) == cib_attr
    def is_current_cib_equal(self, silent = False):
        if self.overwrite:
            return True
        doc,cib = read_cib(cibdump2doc)
        if not doc:
            return False
        if not cib:
            doc.unlink()
            return False
        rc = self.attr_match(cib,'epoch') and \
                self.attr_match(cib,'admin_epoch')
        if not silent and not rc:
            common_warn("CIB changed in the meantime: won't touch it!")
        doc.unlink()
        return rc
    def add_missing_topnodes(self):
        cib_create_topnode = "cibadmin -C -o configuration -X"
        for tag in self.missing_topnodes:
            if not self.topnode[tag].hasChildNodes():
                continue
            if ext_cmd("%s '<%s/>'" % (cib_create_topnode, tag)) != 0:
                common_err("could not create %s in the cib" % tag)
                return False
        return True
    def state_header(self):
        'Print object status header'
        print CibObject.state_fmt % \
            ("","origin","updated","moved","invalid","parent","children")
    def showobjects(self):
        self.state_header()
        for obj in self.cib_objects:
            obj.dump_state()
        if self.remove_queue:
            print "Remove queue:"
            for obj in self.remove_queue:
                obj.dump_state()
    def showqueue(self, title, obj_filter):
        upd_list = self.cib_objs4cibadmin(obj_filter)
        if title == "delete":
            upd_list += self.remove_queue
        if upd_list:
            s = ''
            upd_list = processing_sort_cli(upd_list)
            if title == "delete":
                upd_list = reversed(upd_list)
            for obj in upd_list:
                s = s + " " + obj.obj_string()
            print "%s:%s" % (title,s)
    def showqueues(self):
        'Show what is going to happen on commit.'
        # 1. remove objects (incl. modified constraints)
        self.showqueue("delete", lambda o: 
            o.origin == "cib" and (o.updated or o.recreate) and is_constraint(o.node))
        # 2. update existing objects
        self.showqueue("replace", lambda o: \
            o.origin != 'user' and o.updated and not is_constraint(o.node))
        # 3. create new objects
        self.showqueue("create", lambda o: \
            o.origin == 'user' and not is_constraint(o.node))
        # 4. create objects moved from a container
        self.showqueue("create", lambda o: \
            not o.parent and o.moved and o.origin == "cib")
        # 5. create constraints
        self.showqueue("create", lambda o: is_constraint(o.node) and \
            (((o.updated or o.recreate) and o.origin == "cib") or o.origin == "user"))
    def commit(self):
        'Commit the configuration to the CIB.'
        if not self.doc:
            empty_cib_err()
            return False
        if not self.add_missing_topnodes():
            return False
        # all_committed is updated in the invoked object methods
        self.all_committed = True
        cnt = 0
        # 1. remove objects (incl. modified constraints)
        cnt += self.delete_objects(lambda o: 
            o.origin == "cib" and (o.updated or o.recreate) and is_constraint(o.node))
        # 2. update existing objects
        cnt += self.replace_objects(lambda o: \
            o.origin != 'user' and o.updated and not is_constraint(o.node))
        # 3. create new objects
        cnt += self.create_objects(lambda o: \
            o.origin == 'user' and not is_constraint(o.node))
        # 4. create objects moved from a container
        cnt += self.create_objects(lambda o: \
            not o.parent and o.moved and o.origin == "cib")
        # 5. create constraints
        cnt += self.create_objects(lambda o: is_constraint(o.node) and \
            (((o.updated or o.recreate) and o.origin == "cib") or o.origin == "user"))
        if cnt:
            # reload the cib!
            self.reset()
            self.initialize()
        return self.all_committed
    def cib_objs4cibadmin(self,obj_filter):
        '''
        Filter objects from our cib_objects list. But add only
        top parents.
        For this to work, the filter must not filter out parents.
        That's guaranteed by the updated flag propagation.
        '''
        upd_list = []
        for obj in self.cib_objects:
            if not obj_filter or obj_filter(obj):
                if not obj.parent and not obj in upd_list:
                    upd_list.append(obj)
        return upd_list
    def delete_objects(self,obj_filter):
        cnt = 0
        upd_list = self.cib_objs4cibadmin(obj_filter)
        if not (self.remove_queue + upd_list):
            return 0
        obj_list = processing_sort_cli(self.remove_queue + upd_list)
        for obj in reversed(obj_list):
            if cib_delete_element(obj) == 0:
                if obj in self.remove_queue:
                    self.remove_queue.remove(obj)
                cnt += 1
            else:
                self.all_committed = False
        return cnt
    def create_objects(self,obj_filter):
        upd_list = self.cib_objs4cibadmin(obj_filter)
        if not upd_list:
            return 0
        for obj in upd_list:
            cib_delete_moved_children(obj)
        if cib_update_elements(upd_list) == 0:
            for obj in upd_list:
                obj.reset_updated()
            return len(upd_list)
        else:
            self.all_committed = False
            return 0
    def replace_objects(self,obj_filter):
        cnt = 0
        upd_list = self.cib_objs4cibadmin(obj_filter)
        if not upd_list:
            return 0
        for obj in processing_sort_cli(upd_list):
            #print obj.node.toprettyxml()
            cib_delete_moved_children(obj)
            if cib_replace_element(obj) == 0:
                cnt += 1
                obj.reset_updated()
            else:
                self.all_committed = False
        return cnt
    #
    # initialize cib_objects from CIB
    #
    def save_node(self,node,pnode = None):
        '''
        Need pnode (parent node) acrobacy because cluster
        properties and rsc/op_defaults hold stuff in a
        meta_attributes child.
        '''
        if not pnode:
            pnode = node
        obj = cib_object_map[pnode.tagName][1](pnode.tagName)
        obj.origin = "cib"
        self.cib_objects.append(obj)
        obj.save_xml(node)
    def populate(self):
        "Walk the cib and collect cib objects."
        all_nodes = get_interesting_nodes(self.doc,[])
        if not all_nodes:
            return
        for node in processing_sort(all_nodes):
            if is_defaults(node):
                for c in node.childNodes:
                    if not is_element(c) or c.tagName != "meta_attributes":
                        continue
                    self.save_node(c,node)
            else:
                self.save_node(node)
        for obj in self.cib_objects:
            obj.pull_comments()
        for obj in self.cib_objects:
            if not obj.cli_use_validate():
                obj.nocli = True
        for obj in self.cib_objects:
            obj.update_links()
    def initialize(self):
        if self.doc:
            return True
        if not self.import_cib():
            return False
        sanitize_cib(self.doc)
        show_unrecognized_elems(self.doc)
        self.populate()
        return self.check_structure()
    def init_vars(self):
        self.doc = None  # the cib
        self.topnode = {}
        for t in cib_topnodes:
            self.topnode[t] = None
        self.missing_topnodes = []
        self.cib_attrs = {} # cib version dictionary
        self.cib_objects = [] # a list of cib objects
        self.remove_queue = [] # a list of cib objects to be removed
        self.overwrite = False # update cib unconditionally
    def reset(self):
        if not self.doc:
            return
        self.doc.unlink()
        self.init_vars()
        id_store.clear()
    def find_object(self,obj_id):
        "Find an object for id."
        for obj in self.cib_objects:
            if obj.obj_id == obj_id:
                return obj
        return None
    #
    # tab completion functions
    #
    def id_list(self):
        "List of ids (for completion)."
        return [x.obj_id for x in self.cib_objects]
    def prim_id_list(self):
        "List of primitives ids (for group completion)."
        return [x.obj_id for x in self.cib_objects if x.obj_type == "primitive"]
    def children_id_list(self):
        "List of child ids (for clone/master completion)."
        return [x.obj_id for x in self.cib_objects if x.obj_type in vars.children_tags]
    def rsc_id_list(self):
        "List of resource ids (for constraint completion)."
        return [x.obj_id for x in self.cib_objects \
            if x.obj_type in vars.resource_tags and not x.parent]
    def f_prim_id_list(self):
        "List of possible primitives ids (for group completion)."
        return [x.obj_id for x in self.cib_objects \
            if x.obj_type == "primitive" and not x.parent]
    def f_children_id_list(self):
        "List of possible child ids (for clone/master completion)."
        return [x.obj_id for x in self.cib_objects \
            if x.obj_type in vars.children_tags and not x.parent]
    #
    # a few helper functions
    #
    def find_object_for_node(self,node):
        "Find an object which matches a dom node."
        for obj in self.cib_objects:
            if node.getAttribute("id") == obj.obj_id:
                return obj
        return None
    def resolve_id_ref(self,attr_list_type,id_ref):
        '''
        User is allowed to specify id_ref either as a an object
        id or as attributes id. Here we try to figure out which
        one, i.e. if the former is the case to find the right
        id to reference.
        '''
        obj= self.find_object(id_ref)
        if obj:
            node_l = obj.node.getElementsByTagName(attr_list_type)
            if node_l:
                if len(node_l) > 1:
                    common_warn("%s contains more than one %s, using first" % \
                        (obj.obj_id,attr_list_type))
                id = node_l[0].getAttribute("id")
                if not id:
                    common_err("%s reference not found" % id_ref)
                    return id_ref # hope that user will fix that
                return id
        # verify if id_ref exists
        node_l = self.doc.getElementsByTagName(attr_list_type)
        for node in node_l:
            if node.getAttribute("id") == id_ref:
                return id_ref
        common_err("%s reference not found" % id_ref)
        return id_ref # hope that user will fix that
    def get_property(self,property):
        '''
        Get the value of the given cluster property.
        '''
        for obj in self.cib_objects:
            if obj.obj_type == "property" and obj.node:
                pl = nvpairs2list(obj.node)
                v = find_value(pl, property)
                if v:
                    return v
        return None
    def new_object(self,obj_type,obj_id):
        "Create a new object of type obj_type."
        if id_in_use(obj_id):
            return None
        for xml_obj_type,v in cib_object_map.items():
            if v[0] == obj_type:
                obj = v[1](xml_obj_type,obj_id)
                if obj.obj_id:
                    return obj
                else:
                    return None
        return None
    def mkobj_list(self,mode,*args):
        obj_list = []
        for obj in self.cib_objects:
            f = lambda: obj.filter(*args)
            if not f():
                continue
            if mode == "cli" and obj.nocli:
                obj_cli_err(obj.obj_id)
                continue
            obj_list.append(obj)
        return obj_list
    def has_cib_changed(self):
        return self.mkobj_list("xml","changed") or self.remove_queue
    def verify_constraints(self,cli_list):
        '''
        Check if all resources referenced in a constraint exist
        '''
        rc = True
        head = cli_list[0]
        constraint_id = find_value(head[1],"id")
        for obj_id in referenced_resources_cli(cli_list):
            if not self.find_object(obj_id):
                constraint_norefobj_err(constraint_id,obj_id)
                rc = False
        return rc
    def verify_children(self,cli_list):
        '''
        Check prerequisites:
          a) all children must exist
          b) no child may have other parent than me
          (or should we steal children?)
          c) there may not be duplicate children
        '''
        head = cli_list[0]
        obj_type = head[0]
        obj_id = find_value(head[1],"id")
        c_ids = find_value(head[1],"$children")
        if not c_ids:
            return True
        rc = True
        c_dict = {}
        for child_id in c_ids:
            if not self.verify_child(child_id,obj_type,obj_id):
                rc = False
            if child_id in c_dict:
                common_err("in group %s child %s listed more than once"%(obj_id,child_id))
                rc = False
            c_dict[child_id] = 1
        return rc
    def verify_child(self,child_id,obj_type,obj_id):
        'Check if child exists and obj_id is (or may become) its parent.'
        child = self.find_object(child_id)
        if not child:
            no_object_err(child_id)
            return False
        if child.parent and child.parent.obj_id != obj_id:
            common_err("%s already in use at %s"%(child_id,child.parent.obj_id))
            return False
        if obj_type == "group" and child.obj_type != "primitive":
            common_err("a group may contain only primitives; %s is %s"%(child_id,child.obj_type))
            return False
        if not child.obj_type in vars.children_tags:
            common_err("%s may contain a primitive or a group; %s is %s"%(obj_type,child_id,child.obj_type))
            return False
        return True
    def verify_cli(self,cli_list):
        '''
        Can we create this object given its CLI representation.
        This is not about syntax, we're past that, but about
        semantics.
        Right now we check if the children, if any, are fit for
        the parent. And if this is a constraint, if all
        referenced resources are present.
        '''
        rc = True
        if not self.verify_children(cli_list):
            rc = False
        if not self.verify_constraints(cli_list):
            rc = False
        return rc
    def create_object(self,*args):
        s = []
        s += args
        return self.create_from_cli(CliParser().parse(args)) != None
    def set_property_cli(self,cli_list):
        head_pl = cli_list[0]
        obj_type = head_pl[0].lower()
        pset_id = find_value(head_pl[1],"$id")
        if pset_id:
            head_pl[1].remove(["$id",pset_id])
        else:
            pset_id = cib_object_map[backtrans[obj_type]][3]
        obj = self.find_object(pset_id)
        if not obj:
            if not is_id_valid(pset_id):
                invalid_id_err(pset_id)
                return None
            obj = self.new_object(obj_type,pset_id)
            if not obj:
                return None
            self.topnode[obj.parent_type].appendChild(obj.node)
            obj.origin = "user"
            self.cib_objects.append(obj)
        for n,v in head_pl[1]:
            set_nvpair(obj.node,n,v)
        obj.updated = True
        return obj
    def add_op(self,cli_list):
        '''Add an op to a primitive.'''
        head = cli_list[0]
        # does the referenced primitive exist
        rsc_id = find_value(head[1],"rsc")
        rsc_obj = cib_factory.find_object(rsc_id)
        if not rsc_obj:
            no_object_err(rsc_id)
            return None
        if rsc_obj.obj_type != "primitive":
            common_err("%s is not a primitive" % rsc_id)
            return None
        # check if there is already an op with the same interval
        name = find_value(head[1], "name")
        interval = find_value(head[1], "interval")
        if find_operation(rsc_obj.node,name,interval):
            common_err("%s already has a %s op with interval %s" % \
                (rsc_id, name, interval))
            return None
        # drop the rsc attribute
        head[1].remove(["rsc",rsc_id])
        # create an xml node
        mon_node = mkxmlsimple(head, None, rsc_id)
        # get the place to append it to
        try:
            op_node = rsc_obj.node.getElementsByTagName("operations")[0]
        except:
            op_node = self.createElement("operations")
            rsc_obj.node.appendChild(op_node)
        op_node.appendChild(mon_node)
        # the resource is updated
        rsc_obj.updated = True
        rsc_obj.propagate_updated()
        return rsc_obj
    def create_from_cli(self,cli):
        'Create a new cib object from the cli representation.'
        cli_list = mk_cli_list(cli)
        if not cli_list:
            return None
        if not self.verify_cli(cli_list):
            return None
        head = cli_list[0]
        obj_type = head[0].lower()
        if obj_type in vars.nvset_cli_names:
            return self.set_property_cli(cli_list)
        if obj_type == "op":
            return self.add_op(cli_list)
        obj_id = find_value(head[1],"id")
        if not is_id_valid(obj_id):
            invalid_id_err(obj_id)
            return None
        obj = self.new_object(obj_type,obj_id)
        if not obj:
            return None
        obj.node = obj.cli2node(cli_list)
        if user_prefs.is_check_always() \
                and obj.check_sanity() > 1:
            id_store.remove_xml(obj.node)
            obj.node.unlink()
            return None
        self.topnode[obj.parent_type].appendChild(obj.node)
        self.adjust_children(obj,cli_list)
        obj.origin = "user"
        for child in obj.children:
            # redirect constraints to the new parent
            for c_obj in self.related_constraints(child):
                self.remove_queue.append(c_obj.mkcopy())
                rename_rscref(c_obj,child.obj_id,obj.obj_id)
        # drop useless constraints which may have been created above
        for c_obj in self.related_constraints(obj):
            if silly_constraint(c_obj.node,obj.obj_id):
                self._no_constraint_rm_msg = True
                self._remove_obj(c_obj)
                self._no_constraint_rm_msg = False
        self.cib_objects.append(obj)
        return obj
    def update_moved(self,obj):
        'Updated the moved flag. Mark affected constraints.'
        obj.moved = not obj.moved
        if obj.moved:
            for c_obj in self.related_constraints(obj):
                c_obj.recreate = True
    def adjust_children(self,obj,cli_list):
        '''
        All stuff children related: manage the nodes of children,
        update the list of children for the parent, update
        parents in the children.
        '''
        head = cli_list[0]
        children_ids = find_value(head[1],"$children")
        if not children_ids:
            return
        new_children = []
        for child_id in children_ids:
            new_children.append(self.find_object(child_id))
        self._relink_orphans(obj,new_children)
        obj.children = new_children
        self._update_children(obj)
    def _relink_child(self,obj):
        'Relink a child to the top node.'
        obj.node.parentNode.removeChild(obj.node)
        self.topnode[obj.parent_type].appendChild(obj.node)
        self.update_moved(obj)
        obj.parent = None
    def _update_children(self,obj):
        '''For composite objects: update all children nodes.
        '''
        # unlink all and find them in the new node
        for child in obj.children:
            oldnode = child.node
            child.node = obj.find_child_in_node(child)
            if child.children: # and children of children
                self._update_children(child)
            rmnode(oldnode)
            if not child.parent:
                self.update_moved(child)
            if child.parent and child.parent != obj:
                child.parent.updated = True # the other parent updated
            child.parent = obj
    def _relink_orphans(self,obj,new_children):
        "New orphans move to the top level for the object type."
        for child in obj.children:
            if child not in new_children:
                self._relink_child(child)
    def add_obj(self,obj_type,node):
        obj = self.new_object(obj_type, node.getAttribute("id"))
        if not obj:
            return None
        obj.save_xml(node)
        if not obj.cli_use_validate():
            obj.nocli = True
        obj.update_links()
        obj.origin = "user"
        self.cib_objects.append(obj)
        return obj
    def create_from_node(self,node):
        'Create a new cib object from a document node.'
        if not node:
            return None
        obj_type = cib_object_map[node.tagName][0]
        node = self.doc.importNode(node,1)
        obj = None
        if is_defaults(node):
            for c in node.childNodes:
                if not is_element(c) or c.tagName != "meta_attributes":
                    continue
                obj = self.add_obj(obj_type,c)
        else:
            obj = self.add_obj(obj_type,node)
        if obj:
            self.topnode[obj.parent_type].appendChild(node)
        return obj
    def cib_objects_string(self, obj_list = None):
        l = []
        if not obj_list:
            obj_list = self.cib_objects
        for obj in obj_list:
            l.append(obj.obj_string())
        return ' '.join(l)
    def _remove_obj(self,obj):
        "Remove a cib object and its children."
        # remove children first
        # can't remove them here from obj.children!
        common_debug("remove object %s" % obj.obj_string())
        for child in obj.children:
            #self._remove_obj(child)
            # just relink, don't remove children
            self._relink_child(child)
        if obj.parent: # remove obj from its parent, if any
            obj.parent.children.remove(obj)
        id_store.remove_xml(obj.node)
        rmnode(obj.node)
        obj.invalid = True
        self.add_to_remove_queue(obj)
        self.cib_objects.remove(obj)
        for c_obj in self.related_constraints(obj):
            if is_simpleconstraint(c_obj.node) and obj.children:
                # the first child inherits constraints
                rename_rscref(c_obj,obj.obj_id,obj.children[0].obj_id)
            delete_rscref(c_obj,obj.obj_id)
            if silly_constraint(c_obj.node,obj.obj_id):
                # remove invalid constraints
                self._remove_obj(c_obj)
                if not self._no_constraint_rm_msg:
                    err_buf.info("hanging %s deleted" % c_obj.obj_string())
    def related_constraints(self,obj):
        if not is_resource(obj.node):
            return []
        c_list = []
        for obj2 in self.cib_objects:
            if not is_constraint(obj2.node):
                continue
            if rsc_constraint(obj.obj_id,obj2.node):
                c_list.append(obj2)
        return c_list
    def add_to_remove_queue(self,obj):
        if obj.origin == "cib":
            self.remove_queue.append(obj)
        #print self.cib_objects_string(self.remove_queue)
    def delete_1(self,obj):
        '''
        Remove an object and its parent in case the object is the
        only child.
        '''
        if obj.parent and len(obj.parent.children) == 1:
            self.delete_1(obj.parent)
        if obj in self.cib_objects: # don't remove parents twice
            self._remove_obj(obj)
    def delete(self,*args):
        'Delete a cib object.'
        if not self.doc:
            empty_cib_err()
            return False
        rc = True
        l = []
        for obj_id in args:
            obj = self.find_object(obj_id)
            if not obj:
                no_object_err(obj_id)
                rc = False
                continue
            if is_rsc_running(obj_id):
                common_warn("resource %s is running, can't delete it" % obj_id)
            else:
                l.append(obj)
        if l:
            l = processing_sort_cli(l)
            for obj in reversed(l):
                self.delete_1(obj)
        return rc
    def remove_on_rename(self,obj):
        '''
        If the renamed object is coming from the cib, then it
        must be removed and a new one created.
        '''
        if obj.origin == "cib":
            self.remove_queue.append(obj.mkcopy())
            obj.origin = "user"
    def rename(self,old_id,new_id):
        '''
        Rename a cib object.
        - check if the resource (if it's a resource) is stopped
        - check if the new id is not taken
        - find the object with old id
        - rename old id to new id in all related objects
          (constraints)
        - if the object came from the CIB, then it must be
          deleted and the one with the new name created
        - rename old id to new id in the object
        '''
        if not self.doc:
            empty_cib_err()
            return False
        if id_in_use(new_id):
            return False
        obj = self.find_object(old_id)
        if not obj:
            no_object_err(old_id)
            return False
        if not obj.can_be_renamed():
            return False
        for c_obj in self.related_constraints(obj):
            rename_rscref(c_obj,old_id,new_id)
        self.remove_on_rename(obj)
        rename_id(obj.node,old_id,new_id)
        obj.obj_id = new_id
        id_store.rename(old_id,new_id)
        obj.updated = True
        obj.propagate_updated()
    def erase(self):
        "Remove all cib objects."
        # remove only bottom objects and no constraints
        # the rest will automatically follow
        if not self.doc:
            empty_cib_err()
            return False
        erase_ok = True
        l = []
        for obj in [obj for obj in self.cib_objects \
                if not obj.children and not is_constraint(obj.node) \
                and obj.obj_type != "node" ]:
            if is_rsc_running(obj.obj_id):
                common_warn("resource %s is running, can't delete it" % obj.obj_id)
                erase_ok = False
            else:
                l.append(obj)
        if not erase_ok:
            common_err("CIB erase aborted (nothing was deleted)")
            return False
        self._no_constraint_rm_msg = True
        for obj in l:
            self.delete(obj.obj_id)
        self._no_constraint_rm_msg = False
        remaining = 0
        for obj in self.cib_objects:
            if obj.obj_type != "node":
                remaining += 1
        if remaining > 0:
            common_err("strange, but these objects remained:")
            for obj in self.cib_objects:
                if obj.obj_type != "node":
                    print >> sys.stderr, obj.obj_string()
            self.cib_objects = []
        return True
    def erase_nodes(self):
        "Remove nodes only."
        if not self.doc:
            empty_cib_err()
            return False
        l = [obj for obj in self.cib_objects if obj.obj_type == "node"]
        for obj in l:
            self.delete(obj.obj_id)
    def refresh(self):
        "Refresh from the CIB."
        self.reset()
        self.initialize()

user_prefs = UserPrefs.getInstance()
options = Options.getInstance()
err_buf = ErrorBuffer.getInstance()
vars = Vars.getInstance()
cib_factory = CibFactory.getInstance()
cli_display = CliDisplay.getInstance()
cib_status = CibStatus.getInstance()
id_store = IdMgmt.getInstance()

# vim:ts=4:sw=4:et: