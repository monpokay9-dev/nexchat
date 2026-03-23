from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'nexchat-ultra-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nexchat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt', 'zip', 'mp4', 'mp3'}

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ─────────────────────────── MODELS ───────────────────────────

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar_color = db.Column(db.String(20), default='#6C63FF')
    status = db.Column(db.String(200), default='Hey! I am on NexChat 👋')
    is_online = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default='')
    icon_color = db.Column(db.String(20), default='#FF6584')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('GroupMember', backref='group', lazy=True, cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='group', lazy=True, cascade='all, delete-orphan')


class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, default='')
    file_path = db.Column(db.String(300), default='')
    file_name = db.Column(db.String(200), default='')
    file_type = db.Column(db.String(50), default='')
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    dm_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    client_name = db.Column(db.String(120), default='')
    price = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='PKR')
    month = db.Column(db.Integer, default=datetime.utcnow().month)
    year = db.Column(db.Integer, default=datetime.utcnow().year)
    status = db.Column(db.String(50), default='pending')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        return 'image'
    elif ext in {'mp4', 'avi', 'mov'}:
        return 'video'
    elif ext in {'mp3', 'wav', 'ogg'}:
        return 'audio'
    else:
        return 'document'


COLORS = ['#6C63FF', '#FF6584', '#43D9AD', '#F7C59F', '#E84393', '#00B4D8', '#F4A261', '#7B2D8B']

# ─────────────────────────── AUTH ROUTES ───────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not username or not display_name or not password:
            flash('Sab fields fill karo!', 'error')
            return redirect(url_for('register'))
        if len(username) < 3:
            flash('Username kam az kam 3 characters ka hona chahiye!', 'error')
            return redirect(url_for('register'))
        if password != confirm:
            flash('Passwords match nahi kar rahe!', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Yeh username already le liya gaya hai!', 'error')
            return redirect(url_for('register'))

        import random
        color = random.choice(COLORS)
        user = User(username=username, display_name=display_name, avatar_color=color)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f'NexChat mein khush aamdeed {display_name}! 🎉', 'success')
        return redirect(url_for('chat'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            user.is_online = True
            db.session.commit()
            return redirect(url_for('chat'))
        flash('Username ya password galat hai!', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    current_user.is_online = False
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))


# ─────────────────────────── CHAT ROUTES ───────────────────────────

@app.route('/chat')
@login_required
def chat():
    groups = db.session.query(Group).join(GroupMember, Group.id == GroupMember.group_id)\
        .filter(GroupMember.user_id == current_user.id).all()
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('chat.html', groups=groups, users=users, current_user=current_user)


@app.route('/api/messages/<int:group_id>')
@login_required
def get_group_messages(group_id):
    member = GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    messages = Message.query.filter_by(group_id=group_id).order_by(Message.created_at).all()
    result = []
    for m in messages:
        result.append({
            'id': m.id,
            'content': m.content,
            'file_path': m.file_path,
            'file_name': m.file_name,
            'file_type': m.file_type,
            'sender_id': m.sender_id,
            'sender_name': m.sender.display_name,
            'sender_color': m.sender.avatar_color,
            'time': m.created_at.strftime('%H:%M'),
            'is_me': m.sender_id == current_user.id
        })
    return jsonify(result)


@app.route('/api/dm/<int:user_id>')
@login_required
def get_dm_messages(user_id):
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.dm_to == user_id)) |
        ((Message.sender_id == user_id) & (Message.dm_to == current_user.id))
    ).order_by(Message.created_at).all()
    result = []
    for m in messages:
        result.append({
            'id': m.id,
            'content': m.content,
            'file_path': m.file_path,
            'file_name': m.file_name,
            'file_type': m.file_type,
            'sender_id': m.sender_id,
            'sender_name': m.sender.display_name,
            'sender_color': m.sender.avatar_color,
            'time': m.created_at.strftime('%H:%M'),
            'is_me': m.sender_id == current_user.id
        })
    return jsonify(result)


@app.route('/api/create_group', methods=['POST'])
@login_required
def create_group():
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    members = data.get('members', [])

    if not name:
        return jsonify({'error': 'Group ka naam dalo!'}), 400

    import random
    color = random.choice(COLORS)
    group = Group(name=name, description=description, icon_color=color, created_by=current_user.id)
    db.session.add(group)
    db.session.flush()

    db.session.add(GroupMember(group_id=group.id, user_id=current_user.id, is_admin=True))

    for uid in members:
        if uid != current_user.id:
            db.session.add(GroupMember(group_id=group.id, user_id=int(uid)))

    db.session.commit()
    return jsonify({
        'id': group.id,
        'name': group.name,
        'description': group.description,
        'icon_color': group.icon_color,
        'member_count': len(members) + 1
    })


@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'File nahi mila'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'File select karo'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_')
        filename = timestamp + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        file_type = get_file_type(filename)
        return jsonify({
            'file_path': f'/static/uploads/{filename}',
            'file_name': file.filename,
            'file_type': file_type
        })
    return jsonify({'error': 'File type allowed nahi'}), 400


@app.route('/api/users')
@login_required
def get_users():
    users = User.query.filter(User.id != current_user.id).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'display_name': u.display_name,
        'avatar_color': u.avatar_color,
        'is_online': u.is_online,
        'status': u.status
    } for u in users])


# ─────────────────────────── PROJECTS ROUTES ───────────────────────────

@app.route('/projects')
@login_required
def projects():
    return render_template('projects.html')


@app.route('/api/projects', methods=['GET'])
@login_required
def get_projects():
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    query = Project.query.filter_by(user_id=current_user.id)
    if month:
        query = query.filter_by(month=month)
    if year:
        query = query.filter_by(year=year)
    projects = query.order_by(Project.created_at.desc()).all()
    total = sum(p.price for p in projects)
    return jsonify({
        'projects': [{
            'id': p.id,
            'title': p.title,
            'description': p.description,
            'client_name': p.client_name,
            'price': p.price,
            'currency': p.currency,
            'month': p.month,
            'year': p.year,
            'status': p.status,
            'created_at': p.created_at.strftime('%d %b %Y')
        } for p in projects],
        'total': total,
        'currency': projects[0].currency if projects else 'PKR'
    })


@app.route('/api/projects', methods=['POST'])
@login_required
def add_project():
    data = request.get_json()
    now = datetime.utcnow()
    project = Project(
        title=data.get('title', ''),
        description=data.get('description', ''),
        client_name=data.get('client_name', ''),
        price=float(data.get('price', 0)),
        currency=data.get('currency', 'PKR'),
        month=int(data.get('month', now.month)),
        year=int(data.get('year', now.year)),
        status=data.get('status', 'pending'),
        user_id=current_user.id
    )
    db.session.add(project)
    db.session.commit()
    return jsonify({'success': True, 'id': project.id})


@app.route('/api/projects/<int:pid>', methods=['DELETE'])
@login_required
def delete_project(pid):
    project = Project.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    db.session.delete(project)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/projects/<int:pid>', methods=['PUT'])
@login_required
def update_project(pid):
    project = Project.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    data = request.get_json()
    project.status = data.get('status', project.status)
    project.price = float(data.get('price', project.price))
    project.title = data.get('title', project.title)
    db.session.commit()
    return jsonify({'success': True})


# ─────────────────────────── SOCKET EVENTS ───────────────────────────

@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        current_user.is_online = True
        db.session.commit()
        join_room(f"user_{current_user.id}")
        print(f"[CONNECT] ✅ {current_user.display_name} (ID:{current_user.id}) connected — room: user_{current_user.id}")
        emit('user_status', {'user_id': current_user.id, 'is_online': True}, broadcast=True)


@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        current_user.is_online = False
        db.session.commit()
        print(f"[DISCONNECT] ❌ {current_user.display_name} (ID:{current_user.id}) disconnected")
        emit('user_status', {'user_id': current_user.id, 'is_online': False}, broadcast=True)


@socketio.on('join_group')
def on_join_group(data):
    room = f"group_{data['group_id']}"
    join_room(room)
    print(f"[JOIN GROUP] {current_user.display_name} joined room: {room}")


@socketio.on('join_dm')
def on_join_dm(data):
    ids = sorted([current_user.id, data['user_id']])
    room = f"dm_{ids[0]}_{ids[1]}"
    join_room(room)
    print(f"[JOIN DM] {current_user.display_name} joined room: {room}")


@socketio.on('send_message')
def on_send_message(data):
    msg_type = data.get('type', 'group')
    content = data.get('content', '')
    file_path = data.get('file_path', '')
    file_name = data.get('file_name', '')
    file_type = data.get('file_type', '')

    print(f"[MSG AAYA] sender={current_user.display_name} | type={msg_type} | content={content}")

    if msg_type == 'group':
        group_id = data.get('group_id')
        member = GroupMember.query.filter_by(group_id=group_id, user_id=current_user.id).first()
        if not member:
            print(f"[ERROR] {current_user.display_name} group ka member nahi!")
            return
        msg = Message(content=content, file_path=file_path, file_name=file_name,
                      file_type=file_type, sender_id=current_user.id, group_id=group_id)
        db.session.add(msg)
        db.session.commit()
        room = f"group_{group_id}"
        print(f"[GROUP MSG] Bhej raha hoon room: {room}")
        emit('new_message', {
            'id': msg.id,
            'content': content,
            'file_path': file_path,
            'file_name': file_name,
            'file_type': file_type,
            'sender_id': current_user.id,
            'sender_name': current_user.display_name,
            'sender_color': current_user.avatar_color,
            'time': msg.created_at.strftime('%H:%M'),
            'is_me': False,
            'room_type': 'group',
            'room_id': group_id
        }, to=room)

    elif msg_type == 'dm':
        to_user_id = data.get('to_user_id')
        msg = Message(content=content, file_path=file_path, file_name=file_name,
                      file_type=file_type, sender_id=current_user.id, dm_to=to_user_id)
        db.session.add(msg)
        db.session.commit()

        msg_payload = {
            'id': msg.id,
            'content': content,
            'file_path': file_path,
            'file_name': file_name,
            'file_type': file_type,
            'sender_id': current_user.id,
            'sender_name': current_user.display_name,
            'sender_color': current_user.avatar_color,
            'time': msg.created_at.strftime('%H:%M'),
            'is_me': False,
            'room_type': 'dm',
        }

        print(f"[DM MSG] {current_user.display_name} => user_id:{to_user_id} | content: {content}")
        print(f"[DM MSG] Receiver room: user_{to_user_id}")
        print(f"[DM MSG] Sender room:   user_{current_user.id}")

        emit('new_message', {**msg_payload, 'room_id': current_user.id}, to=f"user_{to_user_id}")
        emit('new_message', {**msg_payload, 'room_id': to_user_id}, to=f"user_{current_user.id}")

        print(f"[DM MSG] ✅ Dono rooms mein bhej diya!")


@socketio.on('typing')
def on_typing(data):
    msg_type = data.get('type', 'group')
    if msg_type == 'group':
        room = f"group_{data['group_id']}"
        room_id = data.get('group_id')
    else:
        to_user_id = data.get('to_user_id')
        room = f"user_{to_user_id}"
        room_id = to_user_id

    emit('typing_indicator', {
        'user_name': current_user.display_name,
        'room_id': room_id
    }, to=room, include_self=False)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✅ NexChat database ready!")
    print("🚀 NexChat server starting on http://localhost:5000")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)