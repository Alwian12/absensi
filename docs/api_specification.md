# Spesifikasi REST API

## Auth
- POST /login
- POST /logout
- POST /register

## Face Recognition
- POST /face/register
- POST /face/verify

## Attendance
- POST /attendance/checkin
- POST /attendance/checkout
- GET /attendance/history

## Journal
- POST /journal
- PUT /journal/{id}
- DELETE /journal/{id}
- GET /journal

## Management
- GET /users
- GET /participants
- GET /supervisors
- GET /dashboard
- GET /reports
