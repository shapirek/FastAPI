import hashlib
import sqlite3

from fastapi import FastAPI, Form, Body, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

import random
from database import get_connection

from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from typing import Optional

from fastapi.middleware.cors import CORSMiddleware 

import uvicorn

# это я пытался настроить регистрацию -- но времени не хватило, так что оставлю на память
SECRET_KEY = "мой-очень-секретный-ключ-12345"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

DEFAULT_EXPIRATION_HOURS = 24
DEFAULT_EXPIRATION_FORMAT = "%Y-%m-%d %H:%M:%S"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# генерация короткого кода из URL
def generate_short_code(url: str) -> str:
    hash_object = hashlib.md5(url.encode())
    return hash_object.hexdigest()[:6]


# подключение к базе данных SQLite
def get_db():
    conn = get_connection()
    return conn, conn.cursor()


# главная страница
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
      <head>
        <title>Сокращатель ссылок</title>
        <style>
          body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
          input, button { padding: 10px; margin-top: 10px; width: 400px; }
          .custom-section { margin: 20px auto; padding: 15px; border: 1px solid #ddd; width: 450px; }
          .nav-buttons { margin-top: 20px; }
          .nav-buttons a { 
              text-decoration: none; 
              color: white; 
              background: #007bff; 
              padding: 10px 20px; 
              border-radius: 4px; 
              margin: 0 5px;
          }
        </style>
      </head>
      <body>
        <h1>Добро пожаловать в сервис сокращения ссылок!</h1>

        <!-- Основная форма -->
        <form action="/shorten" method="post">
          <label for="url">Введите длинный URL:</label><br>
          <input type="text" id="url" name="url" placeholder="https://example.com" required><br>

          <!-- Секция кастомного алиаса -->
          <div class="custom-section">
            <label for="custom_alias">Желаемый псевдоним (необязательно):</label><br>
            <input type="text" id="custom_alias" name="custom_alias" placeholder="my-custom-link">
            <p style="font-size: 12px; color: #666;">Только буквы, цифры и дефисы</p>
          </div>

          <button type="submit">Сократить ссылку</button>
        </form>

        <div class="nav-buttons">
          <a href="/my_urls">Мои URL</a>
        </div>
      </body>
    </html>
    """

@app.post("/shorten", response_class=HTMLResponse)
def shorten_url(
        request: Request,
        response: Response,
        url: str = Form(...),
        custom_alias: Optional[str] = Form(None),
        expires_at: Optional[str] = Form(None)
):
    conn, cursor = get_db()
    error = None

    # валидация кастомного алиаса
    if custom_alias:
        custom_alias = custom_alias.strip()
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
        if not all(char in allowed_chars for char in custom_alias):
            error = "Можно использовать только буквы, цифры и дефисы"
        elif len(custom_alias) < 4 or len(custom_alias) > 32:
            error = "Длина alias должна быть от 4 до 32 символов"
        else:
            cursor.execute("SELECT short_code FROM links WHERE short_code = ?", (custom_alias,))
            if cursor.fetchone():
                error = f"Alias '{custom_alias}' уже занят"

    # определяем время жизни ссылки
    if expires_at:
        try:
            expiration_dt = datetime.strptime(expires_at, DEFAULT_EXPIRATION_FORMAT)
            expires_at_str = expiration_dt.strftime(DEFAULT_EXPIRATION_FORMAT)
        except ValueError:
            error = "Неверный формат даты истечения. Используйте 'YYYY-MM-DD HH:MM:SS'"
    else:
        expiration_dt = datetime.now() + timedelta(hours=DEFAULT_EXPIRATION_HOURS)
        expires_at_str = expiration_dt.strftime("%Y-%m-%d %H:%M:%S")

    if error:
        conn.close()
        return f"""
        <html>
          <head><style>
            body {{ text-align: center; margin-top: 50px; font-family: Arial; }}
            .error {{ color: red; padding: 20px; border: 1px solid red; margin: 20px auto; width: 60%; }}
          </style></head>
          <body>
            <div class="error">
              <h3>Ошибка!</h3>
              <p>{error}</p>
              <a href="/">Попробовать снова</a>
            </div>
          </body>
        </html>
        """

    # поиск существующей записи
    cursor.execute("SELECT short_code FROM links WHERE original_url = ?", (url,))
    existing_link = cursor.fetchone()

    if existing_link:
        short_code = existing_link[0]
    else:
        if custom_alias:
            short_code = custom_alias
        else:
            attempts = 0
            while True:
                salt = str(random.randint(0, 999999)) if attempts > 0 else ""
                short_code = generate_short_code(url + salt)
                cursor.execute("SELECT short_code FROM links WHERE short_code = ?", (short_code,))
                if not cursor.fetchone():
                    break
                attempts += 1
                if attempts > 5:
                    conn.close()
                    return "Ошибка генерации уникальной ссылки"
        try:
            cursor.execute(
                "INSERT INTO links (original_url, short_code, expires_at) VALUES (?, ?, ?)",
                (url, short_code, expires_at_str)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return f"""
            <html>
              <body style="text-align:center; margin-top:50px;">
                <h2 style="color:red;">Ошибка! Псевдоним '{short_code}' уже существует</h2>
                <p><a href="/">Попробовать снова</a></p>
              </body>
            </html>
            """
    conn.close()
    short_url = f"/r/{short_code}"
    html_content = f"""
    <html>
      <head>
        <title>Сокращённая ссылка</title>
        <style>
          body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
          .success-box {{ 
            padding: 20px;
            border: 2px solid #4CAF50;
            border-radius: 5px;
            margin: 20px auto;
            width: 60%;
          }}
          .short-url {{ 
            font-size: 24px; 
            color: #2196F3;
            word-break: break-all;
            margin: 15px 0;
          }}
          .button-group button {{
            margin: 5px;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
          }}
          .delete-btn {{ background-color: #ff4444; color: white; }}
          .update-btn {{ background-color: #ff9800; color: white; }}
          .stats-btn {{ background-color: #4CAF50; color: white; }}
          .nav-buttons a {{
              text-decoration: none; 
              color: white; 
              background: #007bff; 
              padding: 10px 20px; 
              border-radius: 4px; 
              margin: 0 5px;
          }}
          .footnote {{
              font-size: 12px;
              color: #666;
              margin-top: 10px;
          }}
        </style>
      </head>
      <body>
        <div class="success-box">
          <h2>✅ Ссылка успешно создана!</h2>
          <div class="short-url">
            <a href="{short_url}" target="_blank">{short_url}</a>
          </div>
          <div class="button-group">
            <a href="/"><button>Создать новую</button></a>
            <form action="/delete" method="post" style="display: inline;">
              <input type="hidden" name="short_code" value="{short_code}">
              <button type="submit" class="delete-btn">Удалить</button>
            </form>
            <a href="/update/{short_code}"><button class="update-btn">Изменить</button></a>
            <a href="/links/{short_code}/stats"><button class="stats-btn">Статистика</button></a>
          </div>
          <div class="footnote">
            Эта ссылка будет активна до {expires_at_str}
          </div>
          <div class="nav-buttons" style="margin-top: 20px;">
            <a href="/my_urls">Мои URL</a>
          </div>
        </div>
      </body>
    </html>
    """
    existing_cookie = request.cookies.get("my_urls")
    if existing_cookie:
        codes = existing_cookie.split(",")
        if short_code not in codes:
            codes.append(short_code)
    else:
        codes = [short_code]
    response_obj = HTMLResponse(content=html_content)
    response_obj.set_cookie(key="my_urls", value=",".join(codes), httponly=True)
    return response_obj

# обработчик удаления ссылки через POST-запрос
@app.post("/delete", response_class=HTMLResponse)
def delete_link(short_code: str = Form(...)):
    conn, cursor = get_db()
    cursor.execute("SELECT id FROM links WHERE short_code = ?", (short_code,))
    link = cursor.fetchone()

    if not link:
        conn.close()
        return HTMLResponse(f"""
        <html>
          <head><title>Ошибка</title></head>
          <body style="text-align:center; font-family:Arial; margin-top:50px;">
            <h1>Ссылка не найдена</h1>
            <p><a href="/">Вернуться на главную</a></p>
          </body>
        </html>
        """, status_code=404)

    cursor.execute("DELETE FROM links WHERE short_code = ?", (short_code,))
    conn.commit()
    conn.close()
    return f"""
    <html>
      <head>
        <title>Ссылка удалена</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
        </style>
      </head>
      <body>
        <h1>Ссылка удалена</h1>
        <p>Короткая ссылка с кодом {short_code} была успешно удалена.</p>
        <p><a href="/">Вернуться на главную</a></p>
      </body>
    </html>
    """


# обработчик обновления ссылки через PUT (принимает JSON)
@app.put("/links/{short_code}")
def update_link(short_code: str, payload: dict = Body(...)):
    new_url = payload.get("new_url")
    if not new_url:
        return {"detail": "Новый URL не предоставлен"}
    conn, cursor = get_db()
    cursor.execute("SELECT id FROM links WHERE short_code = ?", (short_code,))
    link = cursor.fetchone()
    if not link:
        conn.close()
        return {"detail": "Ссылка не найдена"}
    cursor.execute("UPDATE links SET original_url = ? WHERE short_code = ?", (new_url, short_code))
    conn.commit()
    conn.close()
    return {"detail": "Ссылка обновлена успешно"}


# страница для обновления ссылки – форма с JavaScript для отправки PUT-запроса
@app.get("/update/{short_code}", response_class=HTMLResponse)
def update_form(short_code: str):
    return f"""
    <html>
      <head>
        <title>Обновление ссылки</title>
        <script>
          function updateLink() {{
            const newUrl = document.getElementById("new_url").value;
            fetch("/links/{short_code}", {{
              method: "PUT",
              headers: {{
                "Content-Type": "application/json"
              }},
              body: JSON.stringify({{ "new_url": newUrl }})
            }})
            .then(response => response.json())
            .then(data => {{
              document.getElementById("result").innerText = data.detail;
            }})
            .catch(error => {{
              document.getElementById("result").innerText = "Ошибка обновления";
            }});
          }}
        </script>
        <style>
          body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
          input, button {{ padding: 10px; margin-top: 10px; }}
        </style>
      </head>
      <body>
        <h1>Обновление ссылки</h1>
        <p>Введите новый URL:</p>
        <input type="text" id="new_url" placeholder="https://new-example.com" required>
        <br>
        <button onclick="updateLink()">Обновить ссылку</button>
        <p id="result"></p>
        <p><a href="/">Вернуться на главную</a></p>
      </body>
    </html>
    """


# эндпоинт статистики по ссылке: GET /links/{short_code}/stats
@app.get("/links/{short_code}/stats", response_class=HTMLResponse)
def get_link_stats(short_code: str):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # все данные о ссылке
        cursor.execute(
            """SELECT original_url, created_at, clicks, last_used_at 
            FROM links 
            WHERE short_code = ?""",
            (short_code,)
        )
        link = cursor.fetchone()

        if not link:
            return HTMLResponse(
                content="<h1>Ссылка не найдена</h1>",
                status_code=404
            )

        original_url, created_at, clicks, last_used_at = link

        # форматируем даты
        created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        last_used = (
            datetime.strptime(last_used_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
            if last_used_at
            else "Никогда"
        )

        return f"""
        <html>
          <head>
            <title>Статистика</title>
            <style>
              body {{ font-family: Arial, sans-serif; padding: 20px; }}
              .stats {{ 
                max-width: 600px;
                margin: 0 auto;
                border: 1px solid #ddd;
                padding: 20px;
                border-radius: 8px;
              }}
              table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
              td, th {{ 
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
              }}
              th {{ background-color: #f5f5f5; }}
            </style>
          </head>
          <body>
            <div class="stats">
              <h2>Статистика для ссылки: {short_code}</h2>
              <table>
                <tr>
                  <th>Оригинальный URL</th>
                  <td><a href="{original_url}" target="_blank">{original_url}</a></td>
                </tr>
                <tr>
                  <th>Дата создания</th>
                  <td>{created_at}</td>
                </tr>
                <tr>
                  <th>Переходов</th>
                  <td>{clicks}</td>
                </tr>
                <tr>
                  <th>Последний переход</th>
                  <td>{last_used}</td>
                </tr>
              </table>
              <p style="margin-top: 20px;">
                <a href="/">← На главную</a>
              </p>
            </div>
          </body>
        </html>
        """

    except sqlite3.Error as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    finally:
        conn.close()


# перенаправляем по короткой ссылке на исходный URL с обновлением счетчика кликов и даты последнего использования
@app.get("/r/{short_code}")
def redirect_to_original(short_code: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT original_url, clicks, expires_at FROM links WHERE short_code = ?",
            (short_code,)
        )
        link = cursor.fetchone()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        original_url, clicks, expires_at = link

        # проверка срока действия ссылки
        if expires_at:
            expiration_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expiration_dt:
                # удаляем ссылку, если она просрочена
                cursor.execute("DELETE FROM links WHERE short_code = ?", (short_code,))
                conn.commit()
                raise HTTPException(status_code=404, detail="Link expired")

        cursor.execute(
            """UPDATE links 
            SET clicks = ?, 
                last_used_at = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime') 
            WHERE short_code = ?""",
            (clicks + 1, short_code)
        )
        conn.commit()
        return RedirectResponse(url=original_url)

    except sqlite3.Error as e:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    finally:
        conn.close()

# функция my_urls оставляем без изменений (она уже имеет фиксированный путь /my_urls):
@app.get("/my_urls", response_class=HTMLResponse)
def my_urls(request: Request):
    # получаем поисковый запрос, если он есть
    search_query = request.query_params.get("original_url", "").strip()

    html = f"""
    <html>
      <head>
        <title>Мои URL</title>
        <style>
          body {{ font-family: Arial, sans-serif; padding: 20px; }}
          h1 {{ text-align: center; }}
          .search-form {{ text-align: center; margin-bottom: 20px; }}
          input[type="text"] {{ padding: 10px; width: 300px; }}
          button {{ padding: 10px 20px; }}
          table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
          th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
          th {{ background-color: #f5f5f5; }}
          a.button {{
              display: inline-block;
              padding: 10px 20px;
              margin: 20px 0;
              background: #007bff;
              color: white;
              text-decoration: none;
              border-radius: 4px;
          }}
          .stat-btn {{
              background-color: #4CAF50;
              color: white;
              border: none;
              padding: 5px 10px;
              border-radius: 4px;
              text-decoration: none;
          }}
        </style>
      </head>
      <body>
        <h1>Мои URL</h1>
        <div class="search-form">
          <form action="/my_urls" method="get">
            <input type="text" name="original_url" placeholder="Введите оригинальный или короткий URL" value="{search_query}">
            <button type="submit">Поиск</button>
          </form>
        </div>
    """

    my_urls_cookie = request.cookies.get("my_urls")
    if not my_urls_cookie:
        html += "<p>Вы ещё не создали ни одного URL.</p>"
    else:
        short_codes = my_urls_cookie.split(",")
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in short_codes)
        if search_query:
            pattern = f"%{search_query}%"
            cursor.execute(f"""
                SELECT short_code, original_url, created_at 
                FROM links 
                WHERE short_code IN ({placeholders})
                  AND (original_url LIKE ? OR short_code LIKE ?)
                ORDER BY datetime(created_at) DESC
            """, tuple(short_codes) + (pattern, pattern))
        else:
            cursor.execute(f"""
                SELECT short_code, original_url, created_at 
                FROM links 
                WHERE short_code IN ({placeholders})
                ORDER BY datetime(created_at) DESC
            """, tuple(short_codes))
        links = cursor.fetchall()
        conn.close()
        if links:
            html += """
            <table>
              <tr>
                <th>Короткий код</th>
                <th>Длинный URL</th>
                <th>Дата создания</th>
                <th>Статистика</th>
              </tr>
            """
            for short_code, original_url, created_at in links:
                html += f"""
                <tr>
                  <td><a href="/r/{short_code}" target="_blank">{short_code}</a></td>
                  <td><a href="{original_url}" target="_blank">{original_url}</a></td>
                  <td>{created_at}</td>
                  <td><a href="/links/{short_code}/stats" class="stat-btn" target="_blank">Статистика</a></td>
                </tr>
                """
            html += "</table>"
        else:
            html += "<p>По вашему запросу ничего не найдено.</p>"

    html += """
        <p style="text-align:center;"><a href="/" class="button">← На главную</a></p>
      </body>
    </html>
    """
    return html


@app.get("/links/search", response_class=HTMLResponse)
def search_links(request: Request):
    search_query = request.query_params.get("original_url", "").strip()
    my_urls_cookie = request.cookies.get("my_urls")
    html = """
    <html>
      <head>
        <title>Мои URL - Поиск</title>
        <style>
          body { font-family: Arial, sans-serif; padding: 20px; }
          h1 { text-align: center; }
          .search-form { text-align: center; margin-bottom: 20px; }
          input[type="text"] { padding: 10px; width: 300px; }
          button { padding: 10px 20px; }
          table { width: 100%; border-collapse: collapse; margin-top: 20px; }
          th, td { padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }
          th { background-color: #f5f5f5; }
          a.button { 
              display: inline-block; 
              padding: 10px 20px; 
              margin: 20px 0; 
              background: #007bff; 
              color: white; 
              text-decoration: none; 
              border-radius: 4px; 
          }
        </style>
      </head>
      <body>
        <h1>Мои URL</h1>
        <div class="search-form">
          <form action="/links/search" method="get">
            <input type="text" name="original_url" placeholder="Введите оригинальный или короткий URL" value="{query}">
            <button type="submit">Поиск</button>
          </form>
        </div>
    """.replace("{query}", search_query)

    if not my_urls_cookie:
        html += "<p>Вы ещё не создали ни одного URL.</p>"
    else:
        short_codes = my_urls_cookie.split(",")
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in short_codes)
        if search_query:
            pattern = f"%{search_query}%"
            cursor.execute(f"""
                SELECT short_code, original_url, created_at 
                FROM links 
                WHERE short_code IN ({placeholders})
                  AND (original_url LIKE ? OR short_code LIKE ?)
                ORDER BY datetime(created_at) DESC
            """, tuple(short_codes) + (pattern, pattern))
        else:
            cursor.execute(f"""
                SELECT short_code, original_url, created_at 
                FROM links 
                WHERE short_code IN ({placeholders})
                ORDER BY datetime(created_at) DESC
            """, tuple(short_codes))
        links = cursor.fetchall()
        conn.close()
        if links:
            html += """
            <table>
              <tr>
                <th>Короткий код</th>
                <th>Длинный URL</th>
                <th>Дата создания</th>
              </tr>
            """
            for short_code, original_url, created_at in links:
                html += f"""
                <tr>
                  <td><a href="/r/{short_code}" target="_blank">{short_code}</a></td>
                  <td><a href="{original_url}" target="_blank">{original_url}</a></td>
                  <td>{created_at}</td>
                </tr>
                """
            html += "</table>"
        else:
            html += "<p>По вашему запросу ничего не найдено.</p>"

    html += """
        <p style="text-align:center;"><a href="/" class="button">← На главную</a></p>
      </body>
    </html>
    """
    return html
    
if __name__ == "__main__":  # ← Последние 3 строки в файле
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
