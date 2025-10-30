from fastapi import FastAPI, WebSocket
from app.executor import InteractiveSession
from typing import Dict
import asyncio
from time import time
import shutil
import os
import sys

app = FastAPI()
sessions: Dict[str, Dict] = {}  # sessionId → { "session": InteractiveSession, "last_active": timestamp }

@app.get("/status")
def status():
    return {"active_sessions": len(sessions)}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_expired_sessions())

async def cleanup_expired_sessions(interval=60, timeout=600):
    while True:
        await asyncio.sleep(interval)
        now = time()
        expired = [sid for sid, info in sessions.items() if now - info["last_active"] > timeout]
        for sid in expired:
            try:
                # 세션 정리
                await sessions[sid]["session"].cleanup()
                
                # 세션 딕셔너리에서 제거
                del sessions[sid]

                # 디렉토리 경로: /code/{sessionId}
                dir_path = f"/code/{sid}"
                if os.path.exists(dir_path) and os.path.isdir(dir_path):
                    shutil.rmtree(dir_path)
                    print(f"🧹 세션 {sid} 디렉토리 정리 완료: {dir_path}")
            except Exception as e:
                print(f"⚠️ 세션 {sid} 정리 중 오류 발생: {e}")

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print("✅ WebSocket connected")

    try:
        while True:
            data = await ws.receive_json()
            session_id = data.get("sessionId")
            if not session_id:
                await ws.send_json({"type": "error", "message": "Missing sessionId"})
                continue

            now = time()
            # 메시지 유형에 따라 세션 생성 또는 갱신
            if data.get("type") == "execute_code":
                code = data.get("code", "")
                if not code:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": "No code provided"
                    })
                    continue

                # 디렉토리 생성: /code/{session_id}
                dir_path = f"/code/{session_id}"
                file_path = os.path.join(dir_path, "main.py")

                try:
                    os.makedirs(dir_path, exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(code)

                    # 세션 등록 및 실행
                    session = InteractiveSession(ws, session_id)
                    sessions[session_id] = {
                        "session": session,
                        "last_active": time()
                    }
                    await session.run_with_bwrap(file_path, dir_path)

                except Exception as e:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": f"Failed to prepare or run code: {str(e)}"
                    })

            elif data.get("type") == "submit_code":
                code = data.get("code", "")
                testcases = data.get("testcases", [])
                keywords = data.get("keywords", [])  # 키워드 검사 목록 추가
                print(f"[MAIN] 키워드 수신: {keywords}, 타입: {type(keywords)}", file=sys.stderr)
                
                if not code:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": "No code provided"
                    })
                    continue

                # 디렉토리 및 파일 생성
                dir_path = f"/code/{session_id}"
                file_path = os.path.join(dir_path, "main.py")
                try:
                    os.makedirs(dir_path, exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(code)

                    # 세션 등록 및 grading 실행
                    session = InteractiveSession(ws, session_id)
                    sessions[session_id] = {
                        "session": session,
                        "last_active": now
                    }

                    print(f"[MAIN] run_grading_bwrap 호출 - keywords: {keywords}", file=sys.stderr)
                    try:
                        await session.run_grading_bwrap(file_path, dir_path, testcases, keywords)
                        print(f"[MAIN] run_grading_bwrap 완료", file=sys.stderr)
                    except Exception as e:
                        print(f"[MAIN] run_grading_bwrap 오류: {e}", file=sys.stderr)
                        import traceback
                        traceback.print_exc()

                except Exception as e:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": f"Failed to prepare or grade code: {str(e)}"
                    })


            elif data.get("type") == "execute_file":
                content_id = data.get("contentId")
                user_id = data.get("userId")
                target_file = "main.py"
                real_path = f"/code/{content_id}/{user_id}/{target_file}"
                sandbox_root = f"/code/{content_id}/{user_id}"

                session = InteractiveSession(ws, session_id)
                sessions[session_id] = {
                    "session": session,
                    "last_active": now
                }
                await session.run_with_bwrap(real_path, sandbox_root)

            elif data.get("type") == "execute_grading":
                content_id = data.get("contentId")
                user_id = data.get("userId")
                testcases = data.get("testcases", [])
                target_file = "main.py"
                real_path = f"/code/{content_id}/{user_id}/{target_file}"
                sandbox_root = f"/code/{content_id}/{user_id}"

                session = InteractiveSession(ws, session_id)
                sessions[session_id] = {
                    "session": session,
                    "last_active": now
                }
                await session.run_grading_bwrap(real_path, sandbox_root, testcases)


            elif data.get("type") == "input":
                value = data.get("value", "")
                session_info = sessions.get(session_id)
                if session_info:
                    session_info["last_active"] = now
                    await session_info["session"].send_stdin(value)
                else:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": "Session not found"
                    })
            
            elif data.get("type") == "interrupt":
                session_info = sessions.get(session_id)
                if session_info:
                    await session_info["session"].terminate_process()
                    await ws.send_json({
                        "type": "interrupted",
                        "sessionId": session_id,
                        "value": "▶ 실행이 강제로 중단되었습니다."
                    })
                else:
                    await ws.send_json({
                        "type": "error",
                        "sessionId": session_id,
                        "message": "Session not found"
                    })

            elif data.get("type") == "terminate":
                session_info = sessions.get(session_id)
                if session_info:
                    await session_info["session"].cleanup()
                    del sessions[session_id]

                    dir_path = f"/code/{session_id}"
                    if os.path.exists(dir_path) and os.path.isdir(dir_path):
                        try:
                            shutil.rmtree(dir_path)
                            print(f"세션 {session_id} 디렉토리 정리 완료: {dir_path}")
                        except Exception as e:
                            print(f"디렉토리 삭제 실패: {e}")

    except Exception as e:
        import traceback
        print("WebSocket error:", e)
        traceback.print_exc()

    finally:
        print("⚠️ WebSocket disconnected")

        # 끊긴 WebSocket과 연결된 세션 정리
        for sid, info in list(sessions.items()):
            if info["session"].ws == ws:
                try:
                    await info["session"].cleanup()
                    del sessions[sid]

                    # 디렉토리 경로: /code/{sessionId}
                    dir_path = f"/code/{sid}"
                    if os.path.exists(dir_path) and os.path.isdir(dir_path):
                        shutil.rmtree(dir_path)
                        print(f"🧹 세션 {sid} 디렉토리 정리 완료: {dir_path}")
                except Exception as e:
                    print(f"⚠️ 세션 {sid} 정리 중 오류 발생: {e}")

        await ws.close()

