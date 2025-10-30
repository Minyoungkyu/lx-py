# FROM python:3.11-slim

# WORKDIR /app
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt
# RUN apt update && apt install -y \
#     procps \
#     bubblewrap \
#     libcap2-bin \
#     && apt clean

# COPY app/ app/

# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# FROM python:3.11

# WORKDIR /app
# RUN apt update && apt install -y \
#     procps bubblewrap libcap2-bin \
#     build-essential gfortran libatlas-base-dev python3-dev \
#     && apt clean

# RUN pip install --no-cache-dir pandas numpy fastapi uvicorn[standard]

# COPY app/ app/


# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11

WORKDIR /app
RUN apt update && apt install -y \
    procps bubblewrap libcap2-bin \
    build-essential gfortran libatlas-base-dev python3-dev \
    && apt clean

RUN pip install --no-cache-dir pandas numpy fastapi uvicorn[standard]

COPY app/ app/


CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
