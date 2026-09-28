# cms-p
============EN==============
Video panel management system for displaying announcements, birthdays, etc.
The system allows you to upload images, announcements with specific display periods, and employee birthdays.
You can also upload video clips to be displayed as announcements.
http://IP_ADDRESS:8000/admin — Admin panel
http://IP_ADDRESS:8000/display — Content display page
Switch the operating system to kiosk mode and open http://IP_ADDRESS:8000/display in the browser in full-screen mode.
Launch via Docker (tested on Ubuntu 22.04 + Docker Compose version v5.5.1)
Copy the folder to the server, navigate to the folder, and run:
docker compose up -d --build
=============RU================
Система управления видео панелями для показа оъявлений, дней рождений и тд
В панели можно загружать изображения, объявления с периодом коаза, дни рождения сотрудников. Так же в качестве объявления можно грузить  видеоролики.
http://IP_ADRESS:8000/admin <-админ панель
http://IP_ADRESS:8000/display <- Старница отображения контента
перевести операционную систему в режим киоска, открыть в браузере http://IP_ADRESS:8000/display на полный экран.
Запуск через докер(тестировалось на ubuntu 22.04 + Docker Compose version v5.5.1)
Скопировать папку на сервер, пеерйти в папку выполнить:
docker compose up -d --build
