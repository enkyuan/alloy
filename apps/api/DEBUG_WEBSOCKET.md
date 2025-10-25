# WebSocket Connection Debugging Guide

## Quick Checks

### 1. Verify API Server is Running
```bash
# Check if process is running
ps aux | grep uvicorn

# Check if port 8000 is listening
lsof -i :8000
# or
netstat -an | grep 8000
```

### 2. Check API Logs
```bash
# If running with Docker
docker logs modal-api

# If running directly
# Check the terminal where you started the API
```

### 3. Test WebSocket Connection
```bash
# Using wscat (install: npm install -g wscat)
wscat -c "ws://localhost:8000/api/v1/stt/stream?token=YOUR_TOKEN"

# Using curl (HTTP upgrade)
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: test" \
  "http://localhost:8000/api/v1/stt/stream?token=YOUR_TOKEN"
```

### 4. Verify Imports
```bash
cd apps/api
python test_imports.py
```

### 5. Check for Python Errors
```bash
cd apps/api
python -m py_compile app/routers/speech_to_text_stream.py
python -m py_compile app/services/voice_agent.py
python -m py_compile app/services/spotify_controller.py
python -m py_compile app/services/command_parser.py
```

## Common Issues

### Issue: "Connection Refused"
**Cause**: API server not running
**Solution**: Start the API server
```bash
cd apps/api
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Issue: "Invalid or expired token"
**Cause**: Authentication token is missing or invalid
**Solution**: 
1. Get a valid token from Supabase auth
2. Ensure token is passed in query parameter: `?token=YOUR_TOKEN`

### Issue: "Import Error"
**Cause**: Missing dependencies or syntax errors
**Solution**:
```bash
cd apps/api
poetry install
python test_imports.py
```

### Issue: "No Spotify integration"
**Cause**: User hasn't connected Spotify account
**Solution**: 
1. Connect Spotify in the app settings
2. Verify integration exists in database:
```sql
SELECT * FROM integrations WHERE user_id = 'YOUR_USER_ID' AND service = 'spotify';
```

### Issue: "Database connection error"
**Cause**: Database not accessible
**Solution**:
1. Check DATABASE_URL in .env
2. Verify database is running
3. Test connection:
```bash
cd apps/api
poetry run python -c "from app.database import engine; print(engine.connect())"
```

## Testing Command Execution

### 1. Connect to WebSocket
```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/stt/stream?token=YOUR_TOKEN');

ws.onopen = () => {
  console.log('Connected');
};

ws.onmessage = (event) => {
  console.log('Received:', JSON.parse(event.data));
};
```

### 2. Send Command
```javascript
ws.send(JSON.stringify({
  type: 'command',
  text: 'play bohemian rhapsody by queen'
}));
```

### 3. Expected Response
```json
{
  "type": "command_result",
  "success": true,
  "message": "Now playing 'Bohemian Rhapsody' by Queen",
  "data": { ... },
  "intent": "play_track"
}
```

## Logging

### Enable Debug Logging
In `apps/api/app/config.py`, set:
```python
DEBUG = True
```

### Check Logs for Command Execution
Look for these log messages:
- `"User {user_id} connected to STT stream"`
- `"Received command from user {user_id}: {command_text}"`
- `"Executing command for user {user_id}: intent={intent}, confidence={confidence}"`
- `"Sent command response: {response_type}"`

## Environment Variables

Ensure these are set in `apps/api/.env`:
```bash
DATABASE_URL=postgresql://...
SUPABASE_URL=https://...
SUPABASE_SERVICE_KEY=...
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

## Health Check

Test the API is responding:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "Modal API",
  "version": "1.0.0"
}
```
