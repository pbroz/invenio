# -*- coding: utf-8 -*-
##
## This file is part of Invenio.
## Copyright (C) 2012, 2013 CERN.
##
## Invenio is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## Invenio is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Invenio; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

"""WebDeposit Flask Blueprint"""

import os
import shutil
import json
from glob import iglob
from flask import current_app, \
                  render_template, \
                  request, \
                  jsonify, \
                  redirect, \
                  url_for, \
                  flash, \
                  send_file
from werkzeug.utils import secure_filename
from uuid import uuid1 as new_uuid
from invenio.sqlalchemyutils import db
from invenio.webdeposit_model import WebDepositDraft
from invenio.webdeposit_load_deposition_types import deposition_types, \
                                                     deposition_metadata
from invenio.webinterface_handler_flask_utils import _, InvenioBlueprint

from invenio.config import CFG_WEBDEPOSIT_UPLOAD_FOLDER
from invenio.sherpa_romeo import SherpaRomeoSearch
from invenio.webdeposit_utils import get_current_form, \
                                     get_form, \
                                     draft_field_set, \
                                     draft_field_list_add, \
                                     delete_workflow, \
                                     create_workflow, \
                                     get_latest_or_new_workflow, \
                                     get_workflow, \
                                     draft_field_get_all, \
                                     draft_field_error_check, \
                                     draft_field_get, \
                                     set_form_status, \
                                     get_form_status, \
                                     CFG_DRAFT_STATUS
from invenio.webuser_flask import current_user
from invenio.bibworkflow_engine import CFG_WORKFLOW_STATUS
from invenio.bibworkflow_model import Workflow

blueprint = InvenioBlueprint('webdeposit', __name__,
                             url_prefix='/deposit',
                             config='invenio.websubmit_config',
                             menubuilder=[('main.webdeposit',
                                          _('Deposit'),
                                          'webdeposit.index_deposition_types', 2)],
                             breadcrumbs=[(_('Deposit'), 'webdeposit.index_deposition_types')])


@blueprint.route('/upload/<deposition_type>/<uuid>', methods=['POST'])
@blueprint.invenio_authenticated
def plupload(deposition_type, uuid):
    """ The file is splitted in chunks on the client-side
        and it is merged again on the server-side
    """
    if request.method == 'POST':
        try:
            chunks = request.form['chunks']
            chunk = request.form['chunk']
        except KeyError:
            chunks = None
            pass
        name = request.form['name']
        current_chunk = request.files['file']

        try:
            filename = name + "_" + chunk
        except UnboundLocalError:
            filename = name

        # Check if webdeposit folder exists
        if not os.path.exists(CFG_WEBDEPOSIT_UPLOAD_FOLDER):
            os.makedirs(CFG_WEBDEPOSIT_UPLOAD_FOLDER)

        # Create user filesystem
        # user/deposition_type/uuid/files
        CFG_USER_WEBDEPOSIT_FOLDER = os.path.join(CFG_WEBDEPOSIT_UPLOAD_FOLDER,
                                                  "user_" +
                                                  str(current_user.get_id()))
        if not os.path.exists(CFG_USER_WEBDEPOSIT_FOLDER):
            os.makedirs(CFG_USER_WEBDEPOSIT_FOLDER)

        CFG_USER_WEBDEPOSIT_FOLDER = os.path.join(CFG_USER_WEBDEPOSIT_FOLDER,
                                                  deposition_type)
        if not os.path.exists(CFG_USER_WEBDEPOSIT_FOLDER):
            os.makedirs(CFG_USER_WEBDEPOSIT_FOLDER)

        CFG_USER_WEBDEPOSIT_FOLDER = os.path.join(CFG_USER_WEBDEPOSIT_FOLDER,
                                                  uuid)
        if not os.path.exists(CFG_USER_WEBDEPOSIT_FOLDER):
            os.makedirs(CFG_USER_WEBDEPOSIT_FOLDER)

        # Save the chunk
        current_chunk.save(os.path.join(CFG_USER_WEBDEPOSIT_FOLDER, filename))

        unique_filename = ""

        if chunks is None:  # file is a single chunk
            unique_filename = str(new_uuid()) + name
            old_path = os.path.join(CFG_USER_WEBDEPOSIT_FOLDER, filename)
            file_path = os.path.join(CFG_USER_WEBDEPOSIT_FOLDER, unique_filename)
            os.rename(old_path, file_path)  # Rename the chunk
            size = os.path.getsize(file_path)
            file_metadata = dict(name=name, file=file_path, size=size)
            draft_field_list_add(current_user.get_id(), uuid,
                                 "files", file_metadata)
        elif int(chunk) == int(chunks) - 1:
            '''All chunks have been uploaded!
                start merging the chunks'''

            chunk_files = []
            for filename in iglob(os.path.join(CFG_USER_WEBDEPOSIT_FOLDER, name + '_*')):
                chunk_files.append(filename)

            # Sort files in numerical order
            chunk_files.sort(key=lambda x: int(x.split("_")[-1]))

            unique_filename = str(new_uuid()) + name
            file_path = os.path.join(CFG_USER_WEBDEPOSIT_FOLDER, unique_filename)
            destination = open(file_path, 'wb')
            for chunk in chunk_files:
                shutil.copyfileobj(open(chunk, 'rb'), destination)
                os.remove(chunk)
            destination.close()
            size = os.path.getsize(file_path)
            file_metadata = dict(name=name, file=file_path, size=size)

            draft_field_list_add(current_user.get_id(), uuid,
                                 "files", json.dumps(file_metadata))
    return unique_filename


@blueprint.route('/plupload_delete/<deposition_type>/<uuid>', methods=['GET', 'POST'])
@blueprint.invenio_authenticated
def plupload_delete(deposition_type, uuid):
    if request.method == 'POST':
        files = draft_field_get(current_user.get_id(), uuid, "files")
        result = "File Not Found"
        filename = request.form['filename']
        files = draft_field_get(current_user.get_id(), uuid, "files")
        for index, f in enumerate(files):
            if filename == f['file'].split('/')[-1]:  # get the unique name from the path
                os.remove(f['file'])
                del files[index]
                result = str(files) + "              "
                draft_field_set(current_user.get_id(), uuid, "files", files)
                result = "File " + f['name'] + " Deleted"
                break
    return result


@blueprint.route('/plupload_get_file/<deposition_type>/<uuid>', methods=['GET'])
@blueprint.invenio_authenticated
def plupload_get_file(deposition_type, uuid):
    filename = request.args.get('filename')
    tmp = ""
    files = draft_field_get(current_user.get_id(), uuid, "files")
    for f in files:
        tmp += f['file'].split('/')[-1] + '<br><br>'
        if filename == f['file'].split('/')[-1]:
            return send_file(f['file'], attachment_filename=f['name'], as_attachment=True)

    return "filename: " + filename + '<br>' + tmp


@blueprint.route('/check_status/<deposition_type>/<uuid>/', methods=['GET', 'POST'])
@blueprint.invenio_authenticated
def check_status(deposition_type, uuid):
    form_status = get_form_status(current_user.get_id(), uuid)
    return jsonify({"status": form_status})


@blueprint.route('/<deposition_type>/_autocomplete/<uuid>', methods=['GET', 'POST'])
@blueprint.invenio_authenticated
def autocomplete(deposition_type, uuid):
    """ Returns a list with of suggestions for the field
        based on the current value
    """
    query = request.args.get('term')  # value
    field_type = request.args.get('type')  # field
    limit = request.args.get('limit', 50, type=int)

    form = get_current_form(current_user.get_id(), uuid=uuid)[1]
    form.__dict__["_fields"][field_type].process_data(query)

    #Check if field has an autocomplete function
    if hasattr(form.__dict__["_fields"][field_type], "autocomplete"):
        return jsonify(results=form.__dict__["_fields"][field_type].autocomplete()[:limit])
    else:
        return jsonify(results=[])


@blueprint.route('/<deposition_type>/_ISSN/<uuid>', methods=['GET', 'POST'])
# @cache.cached(timeout=50, key_prefix='issn')
def autocomplete_ISSN_Conditions(deposition_type, uuid):
    query = request.args.get('title')

    s = SherpaRomeoSearch()

    s.search_journal(query)

    response = dict()
    response['issn'] = s.parser.get_issn()
    response['conditions'] = s.parser.get_conditions()

    draft_id, form = get_current_form(current_user.get_id(), uuid=uuid)

    draft_field_set(current_user.get_id(), \
                    draft_id, \
                    "issn", \
                    response['issn'])
    draft_field_set(current_user.get_id(), \
                    draft_id, \
                    "conditions", \
                    response['conditions'])

    return json.dumps(response)


@blueprint.route('/<deposition_type>/_errorCheck/<uuid>')
@blueprint.invenio_authenticated
def error_check(deposition_type, uuid):
    """ Used for field error checking
    """
    value = request.args.get('attribute')
    field_name = request.args.get('name')

    if field_name == "":
        return "{}"

    draft_field_set(current_user.get_id(), uuid, field_name, value)
    check_result = draft_field_error_check(current_user.get_id(), \
                                       uuid, field_name, value)
    try:
        return jsonify(check_result)
    except TypeError:
        return jsonify({"error_message": "", "error": 0})


@blueprint.route('/<deposition_type>/delete/<uuid>')
@blueprint.invenio_authenticated
def delete(deposition_type, uuid):
    """ Deletes the whole deposition with uuid=uuid
        (including form drafts)
        redirects to load another workflow
    """
    delete_workflow(current_user.get_id(), deposition_type, uuid)
    flash(_('Deposition %s deleted!') % (uuid,), 'error')
    return redirect(url_for("webdeposit.index", \
                            deposition_type=deposition_type))


@blueprint.route('/<deposition_type>/new/')
@blueprint.invenio_authenticated
def create_new(deposition_type):
    """ Creates new deposition
    """
    workflow = create_workflow(current_user.get_id(), deposition_type)
    uuid = workflow.get_uuid()
    flash(_('Deposition %s created!') % (uuid,), 'info')
    return redirect(url_for("webdeposit.add", deposition_type=deposition_type, uuid=uuid))


@blueprint.route('/')
def index_deposition_types():
    """ Renders the deposition types (workflows) list """
    current_app.config['breadcrumbs_map'][request.endpoint] = [
                        (_('Home'), '')] + blueprint.breadcrumbs
    drafts = dict(db.session.query(Workflow.name,
                    db.func.count(db.func.distinct(WebDepositDraft.uuid))).\
                  join(WebDepositDraft.workflow).\
                  filter(db.and_(
                    Workflow.user_id == current_user.get_id(),
                    Workflow.status == CFG_WORKFLOW_STATUS['running']
                  )).\
                  group_by(Workflow.name).all())

    return render_template('webdeposit_index_deposition_types.html', \
                           deposition_types=deposition_types,
                           drafts=drafts)


@blueprint.route('/<deposition_type>/')
@blueprint.invenio_authenticated
def index(deposition_type):
    current_app.config['breadcrumbs_map'][request.endpoint] = [
                    (_('Home'), '')] + blueprint.breadcrumbs + [(deposition_type, None)]
    user_id = current_user.get_id()
    drafts = draft_field_get_all(user_id, deposition_type)
    # drafts = WebDepositDraft.query.filter(db.and_(
    #                 WebDepositDraft.user_id == current_user.get_id(),
    #                 WebDepositDraft.deposition_type == deposition_type,
    #                 WebDepositWorkflow.status == CFG_WEBDEPOSIT_WORKFLOW_STATUS['running']
    #               )).group_by(WebDepositDraft.uuid).all()

    return render_template('webdeposit_index.html', drafts=drafts,
                           deposition_type=deposition_type,
                           deposition_types=deposition_types)


@blueprint.route('/<deposition_type>/<uuid>', methods=['GET', 'POST'])
@blueprint.invenio_authenticated
def add(deposition_type, uuid=None):
    """
    FIXME: add documentation
    """

    status = 0

    if deposition_type not in deposition_metadata:
        flash(_('Invalid deposition type.'), 'error')
        return redirect(url_for('.index_deposition_types'))

    elif uuid is None:
        # get the latest one. if there is no workflow created
        # lets create a new workflow with given deposition type
        workflow = get_latest_or_new_workflow(deposition_type)
        uuid = workflow.get_uuid()
        #flash(_('Deposition %s') % (uuid,), 'info')
        return redirect(url_for('.add', deposition_type=deposition_type, uuid=uuid))
    else:
        # get workflow with specific uuid
        workflow = get_workflow(deposition_type, uuid)

    current_app.config['breadcrumbs_map'][request.endpoint] = [
                    (_('Home'), '')] + blueprint.breadcrumbs + \
                    [(deposition_type, 'webdeposit.index',
                     {'deposition_type': deposition_type}),
                     (uuid, 'webdeposit.add',
                     {'deposition_type': deposition_type, 'uuid': uuid})]

    if request.method == 'POST':
        # Save the files
        for (field, uploaded_file) in request.files.items():
            filename = secure_filename(uploaded_file.filename)
            if filename == "":
                continue
            file_path = os.path.join(CFG_WEBDEPOSIT_UPLOAD_FOLDER, filename)
            uploaded_file.save(file_path)
            draft_field_list_add(current_user.get_id(),
                                 uuid,
                                 "files",
                                 file_path)

        # Save form values
        for (field_name, value) in request.form.items():
            if "submit" in field_name.lower():
                continue
            draft_field_set(current_user.get_id(), uuid, field_name, value)

        form = get_form(current_user.get_id(), uuid)
        # Validate form
        if not form.validate():
            # render the form with error messages
            return render_template('webdeposit_add.html',
                                  **workflow.get_output(form_validation=True))

        #Set the latest form status to finished
        set_form_status(current_user.get_id(), uuid, CFG_DRAFT_STATUS['finished'])

    workflow.run()
    status = workflow.get_status()

    if status == 0:
        # render current step of the workflow
        return render_template('webdeposit_add.html', **workflow.get_output())
    elif status == CFG_WORKFLOW_STATUS['finished']:
        flash(_('Deposition %s has been successfully finished.') % (uuid, ),
              'success')
        return redirect(url_for('.index_deposition_types'))
    else:
        flash(_('Deposition %s has return error code %d.') % (uuid, status),
              'error')
        current_app.logger.error('Deposition: %s has return error code: %d' % (uuid, status))
        return redirect(url_for('.index_deposition_types'))