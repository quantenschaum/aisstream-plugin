FROM python:alpine
RUN apk add  --no-cache --update-cache bash curl wget py3-pip wget
ADD . /app
RUN cd /app && pip3 install --no-cache-dir -v -r requirements.txt
WORKDIR /app
EXPOSE 10110
ENTRYPOINT ["python3", "plugin.py"]
CMD ["-h"]
