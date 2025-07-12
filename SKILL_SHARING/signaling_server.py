#!/usr/bin/env python3
import os
import eventlet
import socketio
from wsgiref.util import FileWrapper
from mimetypes import guess_type

# Monkey-patch để Eventlet hoạt động đúng với tất cả I/O
eventlet.monkey_patch()

# Khởi tạo Socket.IO server với logging
sio = socketio.Server(
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)

# Queue đợi pairing và mapping sid→room
waiting_queue = []  # [(sid, topic, level), …]
sid2room = {}      # { sid: room_name, … }

@sio.event
def connect(sid, environ):
    addr = environ.get('REMOTE_ADDR')
    print(f"[CONNECT] {sid} connected from {addr}")

@sio.event
def join(sid, data):
    topic = data.get('topic')
    level = data.get('level')
    print(f"[JOIN] from {sid}: topic={topic!r}, level={level!r}")

    # Validate
    if not topic or not level:
        sio.emit('error', {'message': 'Missing topic or level'}, to=sid)
        return

    # Tìm partner
    for idx, (wsid, wtopic, wlevel) in enumerate(waiting_queue):
        if wtopic == topic and wlevel == level:
            room = f"room_{sid}_{wsid}"
            sid2room[sid] = room
            sid2room[wsid] = room
            sio.enter_room(sid, room)
            sio.enter_room(wsid, room)
            sio.emit('paired', {'partner': wsid}, room=sid)
            sio.emit('paired', {'partner': sid}, room=wsid)
            print(f"[PAIRED] {sid} ↔ {wsid} in {room}")
            waiting_queue.pop(idx)
            return

    # Nếu chưa có partner
    waiting_queue.append((sid, topic, level))
    sio.emit('waiting', to=sid)
    print(f"[QUEUE] {sid} waiting (topic={topic}, level={level})")

@sio.event
def signal(sid, data):
    room = sid2room.get(sid)
    print(f"[SIGNAL] from {sid} to room={room}: keys={list(data.keys())}")
    if room:
        sio.emit('signal', data, room=room, skip_sid=sid)

@sio.event
def chat(sid, msg):
    room = sid2room.get(sid)
    print(f"[CHAT] {sid} → room={room}: {msg}")
    if room:
        sio.emit('chat', msg, room=room, skip_sid=sid)

@sio.event
def leave(sid):
    # Khi client bấm Skip hoặc Leave
    print(f"[LEAVE] {sid} left session")
    # Xóa khỏi waiting_queue nếu còn
    waiting_queue[:] = [(x,t,l) for (x,t,l) in waiting_queue if x != sid]
    # Xóa mapping room
    sid2room.pop(sid, None)

@sio.event
def disconnect(sid):
    print(f"[DISCONNECT] {sid} disconnected")
    # Dọn waiting_queue
    waiting_queue[:] = [(x,t,l) for (x,t,l) in waiting_queue if x != sid]
    # Dọn sid2room
    sid2room.pop(sid, None)

# WSGI app để serve Socket.IO và static files
socketio_app = socketio.WSGIApp(sio)

def static_app(environ, start_response):
    path = environ.get('PATH_INFO','').lstrip('/')
    if path in ('','/'):
        path = 'index.html'
    if os.path.isfile(path):
        mime = guess_type(path)[0] or 'application/octet-stream'
        start_response('200 OK', [('Content-Type', mime)])
        return FileWrapper(open(path,'rb'))
    return None

def app(environ, start_response):
    if environ.get('PATH_INFO','').startswith('/socket.io'):
        return socketio_app(environ, start_response)
    static = static_app(environ, start_response)
    if static:
        return static
    start_response('404 NOT FOUND', [('Content-Type','text/plain')])
    return [b'404 Not Found']

if __name__ == '__main__':
    port = int(os.environ.get('PORT',5000))
    print(f"🚀 Starting server on port {port} …")
    eventlet.wsgi.server(eventlet.listen(('',port)), app)
