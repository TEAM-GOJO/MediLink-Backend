import jwt
from flask import Blueprint, app, request, jsonify, current_app, Response, g
from flask_restful import Api, Resource # used for REST API building
from datetime import datetime
from __init__ import app
from api.jwt_authorize import token_required
from model.user import User
from model.kasm import KasmUser

user_api = Blueprint('user_api', __name__,
                   url_prefix='/api')

# API docs https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(user_api)

class UserAPI:        
    class _ID(Resource):  # Individual identification API operation
        @token_required()
        def get(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Return the current user as a json object '''
            return jsonify(current_user.read())
    
    class _BULK(Resource):  # Users API operation for Create, Read, Update, Delete 
        def post(self):
            ''' Handle bulk user creation by sending POST requests to the single user endpoint '''
            users = request.get_json()
            
            if not isinstance(users, list):
                return {'message': 'Expected a list of user data'}, 400
            
            results = {'errors': []}
            
            with current_app.test_client() as client:
                for user in users:
                    # Set a default password as we don't have it for bulk creation
                    user["password"] = app.config['DEFAULT_PASSWORD']
                    
                    # Simulate a POST request to the single user creation endpoint
                    response = client.post('/api/user', json=user)
                    
                    if response.status_code != 200:  # Assuming success status code is 200
                        results['errors'].append(response.get_json())
                        continue
                
                    uid = user.get('uid')
                    uo = User.query.filter_by(_uid=uid).first()
                    # Process sections if provided
                    if uo is not None:
                        abbreviations = [section["abbreviation"] for section in user.get('sections', [])]
                        if len(abbreviations) > 0:  # Check if the list is not empty
                            so = uo.add_sections(abbreviations)
                            if so is None:
                                results['errors'].append({'message': f'Failed to add sections {abbreviations} to user {uid}'})
            
            return jsonify(results) 
            
    class _CRUD(Resource):  # Users API operation for Create, Read, Update, Delete 
        def post(self): # Create method
            ''' Read data for json body '''
            body = request.get_json()
            
            ''' Avoid garbage in, error checking '''
            # validate name
            name = body.get('name')
            password = body.get('password')
            if name is None or len(name) < 2:
                return {'message': f'Name is missing, or is less than 2 characters'}, 400
            # validate uid
            uid = body.get('uid')
            if uid is None or len(uid) < 2:
                return {'message': f'User ID is missing, or is less than 2 characters'}, 400
            # look for kasm_server_needed
            kasm_server_needed = body.get('kasm_server_needed')
            if kasm_server_needed is None:
                kasm_server_needed = False
            else:
                kasm_server_needed = bool(kasm_server_needed)
                
            # look for additional fields 
            password = body.get('password')
            dob = body.get('dob')

            ''' #1: Key code block, setup USER OBJECT '''
            uo = User(name=name, 
                      uid=uid,
                      kasm_server_needed=kasm_server_needed)
            
            ''' Additional garbage error checking '''
            # set password if provided
            if password is not None:
                uo.set_password(password)
            # convert to date type
            if dob is not None:
                try:
                    uo.dob = datetime.strptime(dob, '%Y-%m-%d').date()
                except:
                    return {'message': f'Date of birth format error {dob}, must be mm-dd-yyyy'}, 400
            
            ''' #2: Key Code block to add user to database '''
            user = uo.create()
            if not user: # failure returns error message
                return {'message': f'Processed {name}, either a format error or User ID {uid} is duplicate'}, 400
            
            # success returns json of user
            if kasm_server_needed:
                KasmUser().post(name, uid, password)
            return jsonify(user.read())

        @token_required()
        def get(self):
            # retrieve the current user from the token_required authentication check  
            current_user = g.current_user
            # current_user extracted from the token using token_required decorator
            users = User.query.all() # extract all users from the database
             
            # prepare a json list of user dictionaries
            json_ready = []  
            for user in users:
                user_data = user.read()
                if current_user.role == 'Admin' or current_user.id == user.id:
                    user_data['access'] = ['rw'] # read-write access control 
                else:
                    user_data['access'] = ['ro'] # read-only access control 
                json_ready.append(user_data)
            
            # return response, a json list of user dictionaries
            return jsonify(json_ready)
        
        @token_required()
        def put(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Read data from the JSON body of the request '''
            body = request.get_json()

            ''' Admin-specific update handling '''
            if current_user.role == 'Admin':
                # Admin requires a User ID to change other users' details
                uid = body.get('uid')
                if uid is None:
                    return {"message": "Admin requires a User ID to change", "data": None, "error": "Bad request"}, 400
                # Find the user by UID
                user = User.query.filter_by(_uid=uid).first()
                if user is None:
                    return {'message': f'User {uid} not found'}, 404
            else:
                # Non-admin users can only update their own details
                user = current_user

            ''' Update user details if provided '''
            # Update name if provided in the request body
            name = body.get('name')
            if name:
                user.name = name

            # Update UID if provided in the request body
            new_uid = body.get('uid')
            # Update date of birth if provided in the request body
            dob = body.get('dob')
            if dob:
                try:
                    user.dob = datetime.strptime(dob, '%Y-%m-%d').date()
                except ValueError:
                    return {"message": f"Date of birth format error {dob}, must be yyyy-mm-dd", "data": None, "error": "Bad request"}, 400

            # Update Kasm server requirement if provided in the request body
            kasm_server_needed = body.get('kasm_server_needed')
            if kasm_server_needed is not None:
                user.kasm_server_needed = bool(kasm_server_needed)

            ''' Update directory if UID changes '''
            user.update_directory(new_uid=new_uid)

            ''' Return the updated user details as a JSON object '''
            return jsonify(user.read())
        
        @token_required("Admin")
        def delete(self): # Delete Method
            body = request.get_json()
            uid = body.get('uid')
            user = User.query.filter_by(_uid=uid).first()
            if user is None:
                return {'message': f'User {uid} not found'}, 404
            json = user.read()
            user.delete() 
            # 204 is the status code for delete with no json response
            return f"Deleted user: {json}", 204 # use 200 to test with Postman
         
    class _Section(Resource):  # Section API operation
        @token_required()
        def get(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Return the current user as a json object '''
            return jsonify(current_user.read_sections())
       
        @token_required() 
        def post(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            
            ''' Read data for json body '''
            body = request.get_json()
            
            ''' Error checking '''
            sections = body.get('sections')
            if sections is None or len(sections) == 0:
                return {'message': f"No sections to add were provided"}, 400
            
            ''' Add sections'''
            if not current_user.add_sections(sections):
                return {'message': f'1 or more sections failed to add, current {sections} requested {current_user.read_sections()}'}, 404
            
            return jsonify(current_user.read_sections())
        
        @token_required()
        def put(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user

            ''' Read data for json body '''
            body = request.get_json()

            ''' Error checking '''
            section_data = body.get('section')
            if not section_data:
                return {'message': 'Section data is required'}, 400
            
            if not section_data.get('abbreviation'):
                return {'message': 'Section abbreviation is required'}, 400
            
            if not section_data.get('year'):
                return {'message': 'Section year is required'}, 400

            ''' Update section year '''
            if not current_user.update_section(section_data):
                return {'message': f'Section {section_data.get("abbreviation")} not found or update failed'}, 404

            return jsonify(current_user.read_sections())
        
        @token_required()
        def delete(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
    
            ''' Read data for json body '''
            body = request.get_json()
    
            ''' Error checking '''
            sections = body.get('sections')
            if sections is None or len(sections) == 0:
                return {'message': f"No sections to delete were provided"}, 400
    
            ''' Remove sections '''
            if not current_user.remove_sections(sections):
                return {'message': f'1 or more sections failed to delete, current {sections} requested {current_user.read_sections()}'}, 404
    
            return {'message': f'Sections {sections} deleted successfully'}, 200
        
    class _Security(Resource):
        def post(self):
            try:
                body = request.get_json()
                if not body:
                    return {
                        "message": "Please provide user details",
                        "data": None,
                        "error": "Bad request"
                    }, 400
                ''' Get Data '''
                uid = body.get('uid')
                if uid is None:
                    return {'message': f'User ID is missing'}, 401
                password = body.get('password')
                if not password:
                    return {'message': f'Password is missing'}, 401
                            
                ''' Find user '''
    
                user = User.query.filter_by(_uid=uid).first()
                
                if user is None or not user.is_password(password):
                    
                    return {'message': f"Invalid user id or password"}, 401
                            
                            # Check if user is found
                if user:
                    try:
                        token = jwt.encode(
                            {"_uid": user._uid},
                            current_app.config["SECRET_KEY"],
                            algorithm="HS256"
                        )
                        resp = Response("Authentication for %s successful" % (user._uid))
                        resp.set_cookie(current_app.config["JWT_TOKEN_NAME"], 
                                token,
                                max_age=3600,
                                secure=True,
                                httponly=True,
                                path='/',
                                samesite='None'  # This is the key part for cross-site requests

                                            # domain="frontend.com"
                         )
                        print(token)
                        return resp 
                    except Exception as e:
                        return {
                                        "error": "Something went wrong",
                                        "message": str(e)
                                    }, 500
                return {
                                "message": "Error fetching auth token!",
                                "data": None,
                                "error": "Unauthorized"
                            }, 404
            except Exception as e:
                 return {
                                "message": "Something went wrong!",
                                "error": str(e),
                                "data": None
                            }, 500
                 
        @token_required()
        def delete(self):
            ''' Invalidate the current user's token by setting its expiry to 0 '''
            current_user = g.current_user
            try:
                # Generate a token with practically 0 age
                token = jwt.encode(
                    {"_uid": current_user._uid, 
                     "exp": datetime.utcnow()},
                    current_app.config["SECRET_KEY"],
                    algorithm="HS256"
                )
                # You might want to log this action or take additional steps here
                
                # Prepare a response indicating the token has been invalidated
                resp = Response("Token invalidated successfully")
                resp.set_cookie(
                    current_app.config["JWT_TOKEN_NAME"], 
                    token,
                    max_age=0,  # Immediately expire the cookie
                    secure=True,
                    httponly=True,
                    path='/',
                    samesite='None'
                )
                return resp
            except Exception as e:
                return {
                    "message": "Failed to invalidate token",
                    "error": str(e)
                }, 500

    # building RESTapi endpoint
    api.add_resource(_ID, '/id')
    api.add_resource(_BULK, '/users')
    api.add_resource(_CRUD, '/user')
    api.add_resource(_Section, '/user/section') 
    api.add_resource(_Security, '/authenticate')          
    