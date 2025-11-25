


-- docker cp test-device.sql cacophony-web-server:/test-device.sql && docker exec cacophony-api sh -c "sudo -i -u postgres psql cacophonytest -f/test-device.sql"
--test-groups
INSERT INTO "Groups" ("id","groupName","createdAt","updatedAt") VALUES (DEFAULT,'test-group','2019-03-14 20:15:23.423 +00:00','2019-03-14 20:15:23.423 +00:00');

--test-password
INSERT INTO "Devices" ("id","deviceName","password","public","createdAt","updatedAt","GroupId",uuid,"saltId") VALUES (DEFAULT,'test-device','$2a$10$LWL.Sr0767v0RmWqcgAKduBXSE2G9T2oIn.W5V1ohtgZQA4kKgR06',false,'2019-03-14 20:17:45.636 +00:00','2019-03-14 20:17:45.636 +00:00',1,0,0);
