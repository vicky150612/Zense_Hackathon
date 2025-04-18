from flask import Flask, render_template, request, redirect, url_for, session
import pyrebase
from google.cloud import firestore
import os
from dotenv import load_dotenv
from flask_socketio import SocketIO, join_room, leave_room, send
import time
import pandas as pd

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
        if "user" in session:
            session.pop("user", None)
        email = request.form["email"]
        password = request.form["password"]
        error = ""
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
                {"username": "", "email": email, "bio": ""}
            )
            return "Signup successful! Please check your email to verify."
        except Exception as e:
            if "INVALID_EMAIL" in str(e):
                error = "Invalid email format. Please enter a valid email."
            elif "WEAK_PASSWORD" in str(e):
                error = "Weak password. Please enter a stronger password."
            elif "EMAIL_NOT_FOUND" in str(e):
                error = "Email not found. Please sign up."
            elif "TOO_MANY_ATTEMPTS_TRY_LATER" in str(e):
                error = "Too many attempts. Please try again later."
            elif "EMAIL_EXISTS" in str(e):
                error = "Email already exists. Please log in."
            return render_template("signup.html", error=error)
    return render_template("signup.html")


# Login Route
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
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
                error = "Email not verified. Please check your inbox."
                return render_template("login.html", error=error)
            # Get UID from the response
            uid = user["localId"]
            # if username == "" return uname.html
            user_ref = db.collection("users").document(uid)
            user_data = user_ref.get().to_dict()
            session["user"] = uid  # Store UID in session
            if user_data["username"] == "":
                return render_template("uname.html", user_id=uid, email=email)
            else:
                return redirect(url_for("main_page", user_id=uid))
        except Exception as e:
            if "EMAIL_NOT_FOUND" in str(e):
                error = "Email not found. Please sign up."
            elif "USER_NOT_FOUND" in str(e):
                error = "User not found. Please sign up."
            elif "INVALID_PASSWORD" in str(e):
                error = "Invalid password. Please enter the correct password."
            elif "USER_DISABLED" in str(e):
                error = "User account is disabled. Please contact support."
            elif "TOO_MANY_ATTEMPTS_TRY_LATER" in str(e):
                error = "Too many attempts. Please try again later."
            elif "INVALID_EMAIL" in str(e):
                error = "Invalid email format. Please enter a valid email."
            elif "INVALID_LOGIN_CREDENTIALS" in str(e):
                error = "Invalid credentials. Please check your email and password."
    # If GET request, render the login page
    if "user" in session:
        return redirect(url_for("main_page", user_id=session["user"]))
    return render_template("login.html", error=error)


# Set Username
@app.route("/username", methods=["POST"])
def set_username():
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    username = request.form["username"]
    # Update username in Firestore
    user_ref = db.collection("users").document(user_id)
    user_ref.update({"username": username})
    # Redirect to main page after setting username
    return redirect(url_for("main_page", user_id=user_id))


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

    # Initialize post data
    post_data = {"title": title, "content": content, "user_id": user_id}

    # Handle profile picture upload
    if "picture" in request.files:
        picture = request.files["picture"]
        if picture and picture.filename:
            # Create upload directory if it doesn't exist
            upload_folder = os.path.join("static", "uploads", "posts")
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)

            # Generate unique filename
            file_ext = os.path.splitext(picture.filename)[1].lower()
            filename = f"post_{user_id}_{int(time.time())}{file_ext}"
            photo_path = os.path.join(upload_folder, filename)
            picture.save(photo_path)

            # Store the path relative to static folder for template rendering
            post_data["image_url"] = f"uploads/posts/{filename}"

    # Store post in Firestore
    db.collection("posts").add(post_data)
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
    if "user" not in session:
        return redirect(url_for("login"))
    user_id = session["user"]
    # Check if the user is authorized to delete the post
    post_ref = db.collection("posts").document(request.form["id"])
    post = post_ref.get()
    if not post.exists:
        return "Post not found."
    post_data = post.to_dict()
    if post_data["user_id"] != user_id:
        return "You are not authorized to delete this post."
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
    upload_folder = os.path.join("static", "uploads/profiles")

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
                updates["profile_picture"] = f"uploads/profiles/{filename}"
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


# Clubs
@app.route("/8bit")
def club_8bit():
    return render_template("/clubs/8bit.html")


@app.route("/e-cell")
def club_ecell():
    return render_template("/clubs/E-Cell.html")


@app.route("/impulse")
def club_impulse():
    return render_template("/clubs/Impulse.html")


@app.route("/parvaaz")
def club_parvaaz():
    return render_template("/clubs/Parvaaz.html")


@app.route("/symphony")
def club_symphony():
    return render_template("/clubs/Symphony.html")


@app.route("/vinci")
def club_vinci():
    return render_template("/clubs/Vinci.html")


@app.route("/zense")
def club_zense():
    return render_template("/clubs/Zense.html")


def menu(file_path):
    df = pd.read_excel(file_path, header=None)

    days = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    organized_menu = {
        day: {"Breakfast": [], "Lunch": [], "Snacks": [], "Dinner": []} for day in days
    }

    current_meal = None

    for _, row in df.iterrows():
        first_cell = str(row[0]).strip().upper() if pd.notna(row[0]) else ""

        if first_cell in ["BREAKFAST", "LUNCH", "SNACKS", "DINNER"]:
            current_meal = first_cell.capitalize()
            continue

        if first_cell.isdigit() or not first_cell or pd.isna(row[0]):
            continue

        if current_meal:
            for i, item in enumerate(row):
                if pd.notna(item) and str(item).strip():
                    organized_menu[days[i]][current_meal].append(str(item).strip())

    for day in organized_menu:
        for meal in list(organized_menu[day]):
            if not organized_menu[day][meal]:
                del organized_menu[day][meal]
            else:
                seen = set()
                organized_menu[day][meal] = [
                    item.title()
                    for item in organized_menu[day][meal]
                    if not (item.lower() in seen or seen.add(item.lower()))
                ]

    return organized_menu


@app.route("/generate_menu")
def generate_menu():
    file_path = r"static\assets\menu.xlsx"
    menu_data = menu(file_path)
    html = render_template(
        "menu.html",
        menu=menu_data,
        days=[
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
    )
    with open(r"templates\current_menu.html", "w") as f:
        f.write(html)
    return "Menu HTML generated successfully"


@app.route("/menu")
def menu_page():
    try:
        return render_template("current_menu.html")
    except Exception as e:
        return "Menu not yet updated."


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
    place_found = request.form["place_found"]
    collect = request.form["collect"]
    contact = request.form["contact"]

    # Initialize item data
    item_data = {
        "place_found": place_found,
        "collect": collect,
        "contact": contact,
        "user_id": user_id,
    }

    # Handle item photo upload
    if "item_photo" in request.files:
        item_photo = request.files["item_photo"]
        if item_photo and item_photo.filename:
            # Create upload directory if it doesn't exist
            upload_folder = os.path.join("static", "uploads", "items")
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)

            # Generate unique filename
            file_ext = os.path.splitext(item_photo.filename)[1].lower()
            filename = f"item_{user_id}_{int(time.time())}{file_ext}"
            photo_path = os.path.join(upload_folder, filename)
            item_photo.save(photo_path)

            # Store the path relative to static folder for template rendering
            item_data["image_url"] = f"uploads/items/{filename}"

    # Store item in Firestore
    db.collection("lost_and_found").add(item_data)
    return redirect(url_for("lost_and_found"))


# Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))


if __name__ == "__main__":
    socketio.run(app, debug=True)
