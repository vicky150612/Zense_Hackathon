from flask import Flask, render_template, request, redirect, url_for, session
import pyrebase
from google.cloud import firestore
import os
from dotenv import load_dotenv
from flask_socketio import SocketIO, join_room, leave_room, send


load_dotenv()
# Pyrebase configuration (replace with your Firebase project details)
config = {
    "apiKey": os.getenv("apiKey"),
    "authDomain": os.getenv("authDomain"),
    "databaseURL": os.getenv("databaseURL"),
    "projectId": os.getenv("projectId"),
    "storageBucket": os.getenv("storageBucket"),
    "messagingSenderId": os.getenv("messagingSenderId"),
    "appId": os.getenv("appId"),
    "measurementId": os.getenv("measurementId"),
}


# Initialize Pyrebase
firebase = pyrebase.initialize_app(config)
auth = firebase.auth()

# Initialize Firestore client with service account key
db = firestore.Client.from_service_account_json("serviceAccountKey.json")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("secretKey")

# Initialize SocketIO
socketio = SocketIO(app)


# Home Page
@app.route("/")
def home():
    return render_template("home.html")


# Signup Route
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        username = request.form["username"]
        try:
            # Create user with Pyrebase
            user = auth.create_user_with_email_and_password(email, password)
            # Get ID token and UID from the response
            id_token = user["idToken"]
            uid = user["localId"]
            # Send verification email using Pyrebase
            auth.send_email_verification(id_token)
            # Store user data in Firestore
            db.collection("users").document(uid).set(
                {"username": username, "email": email, "bio": ""}
            )
            return "Signup successful! Please check your email to verify."
        except Exception as e:
            return f"Error: {str(e)}"
    return render_template("signup.html")


# Login Route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Check if user is already logged in
        if "user" in session:
            return redirect(url_for("main_page", user_id=session["user"]))
        # Get email and password from the form
        email = request.form["email"]
        password = request.form["password"]
        try:
            # Sign in user with Pyrebase
            user = auth.sign_in_with_email_and_password(email, password)
            # Get ID token from the response
            id_token = user["idToken"]
            # Fetch user account info to check email verification
            account_info = auth.get_account_info(id_token)
            # Extract email verification status (nested in 'users' list)
            email_verified = account_info["users"][0]["emailVerified"]
            if not email_verified:
                return "Please verify your email before logging in."
            # Get UID from the response
            uid = user["localId"]
            session["user"] = uid  # Store UID in session
            return redirect(url_for("main_page", user_id=uid))
        except Exception as e:
            return f"Error: {str(e)}"
    # If GET request, render the login page
    if "user" in session:
        return redirect(url_for("main_page", user_id=session["user"]))
    return render_template("login.html")


# Main Page (Hub after login)
@app.route("/main_page")
def main_page():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    return render_template("main_page.html", user_id=user_id)


# Posts
@app.route("/posts")
def posts():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Fetch posts from Firestore and Show all posts to the user
    posts_ref = db.collection("posts")
    posts = posts_ref.stream()
    posts_list = []
    for post in posts:
        post_data = post.to_dict()
        post_data["id"] = post.id
        posts_list.append(post_data)
    return render_template("posts.html", user_id=user_id, posts=posts_list)


# Create Post
@app.route("/create_post", methods=["POST"])
def create_post():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    title = request.form["title"]
    content = request.form["content"]
    photo = request.files["profile_picture"]
    # Save the photo to uploads folder with name = user_id
    upload_folder = "uploads"
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    photo_path = os.path.join(upload_folder, f"{user_id}.jpg")
    photo.save(photo_path)
    # Store post in Firestore
    db.collection("posts").add({"title": title, "content": content, "user_id": user_id})
    return redirect(url_for("posts"))


# View Post
@app.route("/post/<post_id>")
def view_post(post_id):
    # Fetch post from Firestore
    post_ref = db.collection("posts").document(post_id)
    post = post_ref.get()
    if not post.exists:
        return "Post not found."
    post_data = post.to_dict()
    post_data["id"] = post.id
    # Fetch user data from Firestore
    user_ref = db.collection("users").document(post_data["user_id"])
    user_data = user_ref.get().to_dict()
    post_data["user"] = user_data
    return render_template(
        "view_post.html", post=post_data, user_data=user_data, user_id=session["user"]
    )


# Delete Post
@app.route("/delete_post", methods=["POST"])
def delete_post():
    post_id = request.form["id"]
    # Delete post from Firestore
    db.collection("posts").document(post_id).delete()
    return redirect(url_for("posts", user_id=session["user"]))


# Ride Share
@app.route("/ride_share")
def rideshare():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Fetch rides from Firestore
    rides_ref = db.collection("rides")
    rides = rides_ref.stream()
    rides_list = []
    for ride in rides:
        ride_data = ride.to_dict()
        ride_data["id"] = ride.id
        rides_list.append(ride_data)
    return render_template("ride_share.html", user_id=user_id, rides=rides_list)


# Create Ride
@app.route("/create_ride", methods=["POST"])
def create_ride():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    ride_data = {
        "from": request.form["from"],
        "to": request.form["to"],
        "date": request.form["date"],
        "time": request.form["time"],
        "contact": request.form["contact"],
        "user_id": user_id,
    }

    # Store ride in Firestore
    db.collection("rides").add(ride_data)
    return redirect(url_for("rideshare"))


# Delete ride
@app.route("/delete_ride/<ride_id>")
def delete_ride(ride_id):
    if "user" not in session:
        return redirect(url_for("login"))
    # Delete ride from Firestore
    db.collection("rides").document(ride_id).delete()
    return redirect(url_for("rideshare"))


@app.route("/messaging/<user_id>", methods=["GET", "POST"])
def messaging(user_id):
    if "user" not in session or session["user"] != user_id:
        return redirect(url_for("login"))
    user_ref = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict()
    username = user_data["username"]
    # Fetch messages for the room 'chat_room'
    messages_ref = (
        db.collection("messages").where("room", "==", "chat_room").order_by("timestamp")
    )
    messages = messages_ref.stream()
    messages_list = []
    for msg in messages:
        msg_data = msg.to_dict()
        messages_list.append(f"{msg_data['username']}: {msg_data['content']}")
    return render_template(
        "messaging.html", user_id=user_id, username=username, messages=messages_list
    )


# SocketIO Event Handlers
@socketio.on("join")
def on_join(data):
    room = data["room"]
    join_room(room)


@socketio.on("leave")
def on_leave(data):
    room = data["room"]
    leave_room(room)
    send(f"User has left the room.", to=room)


@socketio.on("message")
def handle_message(data):
    room = data["room"]
    user_id = data["user_id"]
    username = data["username"]
    content = data["content"]

    # Store in Firestore
    message_data = {
        "room": room,
        "user_id": user_id,
        "username": username,
        "content": content,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    db.collection("messages").add(message_data)

    # Broadcast the formatted message
    formatted_message = f"{username}: {content}"
    send(formatted_message, to=room)


# Profile
@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Fetch user data from Firestore
    user_ref = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict()
    if not user_data:
        return "User not found."
    return render_template("profile.html", user_id=user_id, user=user_data)


# Edit Profile


@app.route("/edit_profile", methods=["POST"])
def edit_profile():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]

    # Get bio from form
    bio = request.form.get("bio", "")

    # Handle profile picture upload
    upload_folder = os.path.join("static", "uploads")

    # Make sure the uploads directory exists
    if not os.path.exists(upload_folder):
        try:
            os.makedirs(upload_folder)
            print(f"Created directory: {upload_folder}")
        except Exception as e:
            print(f"Error creating directory: {e}")
            return f"Error creating uploads directory: {e}"

    profile_picture = request.files.get("profile_picture")
    updates = {"bio": bio}

    if profile_picture and profile_picture.filename:
        # Validate file type
        allowed_extensions = {".png", ".jpg", ".jpeg"}
        file_ext = os.path.splitext(profile_picture.filename)[1].lower()

        if file_ext in allowed_extensions:
            try:
                filename = f"{user_id}{file_ext}"
                photo_path = os.path.join(upload_folder, filename)
                profile_picture.save(photo_path)
                print(f"Saved image to: {photo_path}")

                # Store the path relative to static folder
                updates["profile_picture"] = f"uploads/{filename}"
            except Exception as e:
                print(f"Error saving file: {e}")
                return f"Error saving profile picture: {e}"

    # Update user data in Firestore
    try:
        user_ref = db.collection("users").document(user_id)
        user_ref.update(updates)
        print(f"Updated user profile with: {updates}")
    except Exception as e:
        print(f"Error updating profile: {e}")
        return f"Error updating profile in database: {e}"

    return redirect(url_for("profile"))


# Change Password
@app.route("/change_password")
def change_password():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Fetch user data from Firestore
    user_ref = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict()
    auth.send_password_reset_email(user_data["email"])
    return "Password reset email sent. Please check your inbox. <br> <a href='/'>Go to Home</a>"


# Club
@app.route("/club")
def club():
    return render_template("club.html")


@app.route("/club/<club_id>")
def clubs(club_id):
    return render_template(club_id + ".html")


# Lost and Found
@app.route("/lost_and_found")
def lost_and_found():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Fetch lost and found items from Firestore
    items_ref = db.collection("lost_and_found")
    items = items_ref.stream()
    items_list = []
    for item in items:
        item_data = item.to_dict()
        item_data["id"] = item.id
        items_list.append(item_data)
    return render_template("lost_and_found.html", user_id=user_id, items=items_list)


# Create Lost and Found Item
@app.route("/create_lost_item", methods=["POST"])
def create_lost_item():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    photo_url = request.form["photo"]
    place_found = request.form["place_found"]
    collect = request.form["collect"]
    contact = request.form["contact"]
    # Store item in Firestore
    item_data = {
        "photo_url": photo_url,
        "place_found": place_found,
        "collect": collect,
        "contact": contact,
        "user_id": user_id,
    }
    db.collection("lost_and_found").add(item_data)
    return redirect(url_for("lost_and_found"))


# Menu
@app.route("/menu")
def menu():
    return render_template("menu.html")


# Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))


if __name__ == "__main__":
    socketio.run(app, debug=True)
