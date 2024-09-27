import identity.web
import requests
from flask import Flask, redirect, render_template, request, session, url_for
from flask_session import Session
import json 

import app_config

__version__ = "0.0.1"  # The version of this sample, for troubleshooting purpose

app = Flask(__name__)
app.config.from_object(app_config)
assert app.config["REDIRECT_PATH"] != "/", "REDIRECT_PATH must not be /"
Session(app)

# This section is needed for url_for("foo", _external=True) to automatically
# generate http scheme when this sample is running on localhost,
# and to generate https scheme when it is deployed behind reversed proxy.
# See also https://flask.palletsprojects.com/en/2.2.x/deploying/proxy_fix/
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.jinja_env.globals.update(Auth=identity.web.Auth)  # Useful in template for B2C
auth = identity.web.Auth(
    session=session,
    authority=app.config["AUTHORITY"],
    client_id=app.config["CLIENT_ID"],
    client_credential=app.config["CLIENT_SECRET"],
)


@app.route("/login")
def login():
    return render_template("login.html", version=__version__, **auth.log_in(
        scopes=app_config.FABRIC_SCOPE, # Have user consent to scopes during log-in
        redirect_uri=url_for("auth_response", _external=True), # Optional. If present, this absolute URL must match your app's redirect_uri registered in Azure Portal
        prompt="select_account",  # Optional. More values defined in  https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest
        ))


@app.route(app_config.REDIRECT_PATH)
def auth_response():
    result = auth.complete_log_in(request.args)
    if "error" in result:
        return render_template("auth_error.html", result=result)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    return redirect(auth.log_out(url_for("index", _external=True)))


@app.route("/")
def index():
    if not (app.config["CLIENT_ID"] and app.config["CLIENT_SECRET"]):
        # This check is not strictly necessary.
        # You can remove this check from your production code.
        return render_template('config_error.html')
    if not auth.get_user():
        return redirect(url_for("login"))
    return render_template('index.html', user=auth.get_user(), version=__version__)


@app.route("/call_downstream_api")
def call_downstream_api():
    #Using an incorrect scope or mixed and matched "namespaces" for scope will cause the API to barf.
    #Try it out by changeing to FABRIC_SCOPE or merging GRAPH_SCOPE and FABRIC_SCOPE
    token = auth.get_token_for_user(app_config.GRAPH_SCOPE)

    if "error" in token:
        print(f"Error occured: {token}")
        return redirect(url_for("login"))
    # Use access token to call downstream api
    api_result = requests.get(
        app_config.GRAPH_ENDPOINT,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        timeout=30,
    ).json()
    return render_template('display.html', result=api_result)

@app.route("/call_workspace_api")
def call_workspace_api():
    token = auth.get_token_for_user(app_config.FABRIC_SCOPE)
    if "error" in token:
        return redirect(url_for("login"))
    # Use access token to call downstream api
    api_result = requests.get(
        app_config.WORKSPACE_ENDPOINT,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        timeout=30,
    ).json()

    #Not implemented long lists/continuation tokens , page 1 only
    session['workspaces'] = api_result['workspaces']
    return render_template('display.html', result=api_result)

@app.route("/call_lakehouse_api")
def call_lakehouse_api():
    token = auth.get_token_for_user(app_config.FABRIC_SCOPE)
    if "error" in token:
        return redirect(url_for("login"))
    
    if "workspaces" not in session:
        return render_template('display.html', result=["Please get workspaces before listing lakehouses"])

    lakehouses={}
    print(f"Workspaces are: {session["workspaces"]}")
    for workspace in  session["workspaces"]:
        # Use access token to call downstream api
        print(f"Processing lakehouse list for workspace : {json.dumps(workspace)}")
        api_result = requests.get(
            app_config.LAKEHOUSE_ENDPOINT.format(WORKSPACE_ID=workspace["id"]),
            headers={'Authorization': 'Bearer ' + token['access_token']},
            timeout=30,
        ).json()

        if "error" in api_result:
            print(f"Error occured: {api_result}")
            return render_template('display.html', result=api_result)

        lakehouses[f"Workspace:{workspace['name']} ({workspace['id']})"]=api_result

    session['lakehouses'] = lakehouses
    return render_template('display.html', result=lakehouses)

@app.route("/call_lakehouse_tables_api")
def call_lakehouse_tables_api():
    token = auth.get_token_for_user(app_config.FABRIC_SCOPE)
    if "error" in token:
        return redirect(url_for("login"))
 
    if "lakehouses" not in session:
        return render_template('display.html', result=["Please get list of lakehouses before listing tables"])

    tables={}
    for workspace in session["lakehouses"].keys():
        print(f"Processing workspace: {workspace}")
        for lakehouse in session["lakehouses"][workspace]["value"]:
            # Use access token to call downstream api
            api_result = requests.get(
                app_config.TABLES_ENDPOINT.format(WORKSPACE_ID=lakehouse["workspaceId"],LAKEHOUSE_ID=lakehouse["id"]),
                headers={'Authorization': 'Bearer ' + token['access_token']},
                timeout=30,
            ).json()

            tables[f"{workspace} / Lakehouse:{lakehouse['displayName']} ({lakehouse['id']})"] = api_result


    session['tables'] = tables
    return render_template('display.html', result=tables)


if __name__ == "__main__":
    app.run()
