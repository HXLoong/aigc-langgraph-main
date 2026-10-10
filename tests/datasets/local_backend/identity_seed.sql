-- #169：本地合成身份与公共证券夹具。没有真实成员、密码、token、订单或真实授权关系。
-- INSERT IGNORE 保留已有记录；最后五项校验不满足时由导入器回滚整个事务。
INSERT IGNORE INTO chat_room_config
(id,room_id,room_name,numbers,security_fence,is_receive,is_multimodal,enable,creator,updater)
VALUES (923001,'local-eval-room-923','本地隔离评估群',1,0,0,0,1,'local-seed','local-seed');
INSERT IGNORE INTO chat_room_member
(id,room_id,uid,nickname,is_present,creator,updater)
VALUES ('local-eval-member-923','local-eval-room-923','local-eval-user-923','合成评估用户',1,'local-seed','local-seed');
INSERT IGNORE INTO chat_room_user_config
(id,user_uin,allowed_query,allowed_order,is_associa,type,room_id,creator,updater)
VALUES (923001,'local-eval-user-923',1,1,0,1,'local-eval-room-923','local-seed','local-seed');
INSERT IGNORE INTO stock_authorization_users
(id,user_id,username,platform,access_level,trading_account,tradin_password,authorization_code,remark,enabled,creator,updater)
VALUES (923001,'local-eval-user-923','合成评估用户','GOATS',1,'LOCAL-INERT-923',NULL,NULL,'仅本地GOATS失败边界；无真实授权',1,'local-seed','local-seed');
INSERT IGNORE INTO stock_securities_instrument
(id,ins_family,ins_sht_desc,ins_lng_desc,currency,wind_code,wind_code_no_suffix,wind_code_no_zero,wind_code_no_suffix_no_zero,`exchange`,transaction_type_list,tenant_id,per_unit,creator,updater)
VALUES
(923001,'EQUITY','贵州茅台','贵州茅台','CNY','600519.SH','600519','600519.SH','600519','SH','["A_SHARE"]',1,100,'local-seed','local-seed'),
(923002,'EQUITY','腾讯控股','腾讯控股','HKD','0700.HK','0700','700.HK','700','HK','["HK_STOCK"]',1,100,'local-seed','local-seed');
SELECT 'chat_room_config',COUNT(*),1 FROM chat_room_config
WHERE id=923001 AND room_id='local-eval-room-923' AND creator='local-seed';
SELECT 'chat_room_member',COUNT(*),1 FROM chat_room_member
WHERE id='local-eval-member-923' AND room_id='local-eval-room-923' AND uid='local-eval-user-923' AND is_present=1 AND creator='local-seed';
SELECT 'chat_room_user_config',COUNT(*),1 FROM chat_room_user_config
WHERE id=923001 AND room_id='local-eval-room-923' AND user_uin='local-eval-user-923' AND allowed_query=1 AND allowed_order=1 AND creator='local-seed';
SELECT 'stock_authorization_users',COUNT(*),1 FROM stock_authorization_users
WHERE id=923001 AND user_id='local-eval-user-923' AND trading_account='LOCAL-INERT-923' AND tradin_password IS NULL AND authorization_code IS NULL AND enabled=1 AND creator='local-seed';
SELECT 'stock_securities_instrument',COUNT(*),2 FROM stock_securities_instrument
WHERE creator='local-seed' AND ins_family='EQUITY' AND JSON_VALID(transaction_type_list)
AND ((id=923001 AND wind_code='600519.SH' AND ins_sht_desc='贵州茅台') OR (id=923002 AND wind_code='0700.HK' AND ins_sht_desc='腾讯控股'));
