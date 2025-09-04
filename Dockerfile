FROM python:alpine
RUN apk add  --no-cache --update-cache bash git curl wget py3-pip wget
RUN git clone https://github.com/quantenschaum/aisstream-plugin /app
RUN cd /app && pip3 install --no-cache-dir -v -r requirements.txt
WORKDIR /app
EXPOSE 10110
CMD ./plugin.py 54 8 30 -k apikey
