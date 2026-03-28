FROM python:3.11-slim
WORKDIR /app

# 1. Yeh line Python ke output ko directly logs mein bhejti hai bina delay ke.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

# 2. --no-cache-dir lagane se pip purana kachra use nahi karega aur memory bachegi.
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces specifically 7860 port aur user id 1000 prefer karte hain permissions ke liye
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

EXPOSE 7860
CMD ["python", "main.py"]
