server {
    listen      80;     # 监听端口80

    root       /srv/awesome/www;
    access_log /srv/awesome/log/access_log;
    error_log  /srv/awesome/log/error_log;

    # server_name awesome.liaoxuefeng.com;

    client_max_body_size 1m;    # 允许客户端请求的最大单文件字节数

    gzip            on;     # 开启 gzip 模块
    gzip_min_length 1024;   # 设置允许压缩的页面最小字节数，默认是0，即对所有页面都压缩
    gzip_buffers    4 8k;   # 设置系统获取几个单位的缓存用于存储gzip的压缩结果数据流。4 8k代表以8k为单位，按照原始数据大小以8k为单位的4倍申请内存
    gzip_types      text/css application/x-javascript application/json; # 匹配MIME类型进行压缩

    sendfile on;

    location /favicon.ico {    # 处理静态文件 /favicon.ico
        root /srv/awesome/www;
    }

    location ~ ^\/static\/.*$ {     # 处理静态资源(正则匹配)， ~：区分大小写的匹配
        root /srv/awesome/www;
    }

	# 动态请求转发到9000端口:
    # 因为所有的地址都以 / 开头，所以这条规则将匹配到所有请求
    # 但是正则和最长字符串会优先匹配
    location / {
        proxy_pass       http://127.0.0.1:9000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}