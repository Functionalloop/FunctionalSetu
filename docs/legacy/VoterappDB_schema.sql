-- Schema extracted from VoterappDB.db (SQLite)

-- table: activation
CREATE TABLE "activation" (
	`key_desktop`	TEXT,
	`key_mobile`	TEXT,
	`username`	TEXT,
	`password`	TEXT,
	`cpuid`	TEXT,
	`activation_type`	INTEGER,
	`activated`	INTEGER,
	`blocked`	INTEGER
);

-- table: activation_details
CREATE TABLE "activation_details" (
	`device_type`	TEXT,
	`deviceid`	TEXT,
	`candidate_name`	TEXT,
	`username`	TEXT,
	`email_id`	TEXT,
	`contactno`	TEXT,
	`updated`	INTEGER
);

-- table: activation_types
CREATE TABLE "activation_types" (
	`id`	INTEGER,
	`description`	TEXT
);

-- table: applicationinfo
CREATE TABLE "applicationinfo" (
	`app_id`	INTEGER,
	`election_id`	INTEGER,
	`electiontype`	INTEGER,
	`election_identifier`	TEXT,
	`l_electionname`	TEXT,
	`e_electionname`	TEXT,
	`prabhagno`	TEXT,
	`brandname`	TEXT,
	`marketed_by`	TEXT,
	`l_message_start`	TEXT,
	`e_message_start`	TEXT,
	`l_message_end`	TEXT,
	`e_message_end`	TEXT,
	`data_server_url`	TEXT,
	`survey_server_url`	TEXT,
	`photo_server_url`	TEXT,
	`is_photo_allowed`	INTEGER,
	`is_secure_download`	INTEGER,
	`is_survey`	INTEGER,
	`is_all_in_one`	INTEGER,
	`contactno`	TEXT,
	`is_slip_print`	INTEGER,
	`is_surname_available`	INTEGER,
	`is_bluetooth_printer`	INTEGER,
	`middle_name_seperator`	TEXT,
	`is_special_search`	INTEGER
, is_MobApp_MobileNo_MasterImport BOOLEAN, is_otp BOOLEAN, is_allow_change_slip BOOLEAN, is_sync_slip_image BOOLEAN, is_MobileNo_Master_Enabled BOOLEAN, is_aachar_sanhita BOOLEAN);

-- table: area_type
CREATE TABLE "area_type" (
	"area_type_id" TEXT,
	"area_type_name"	TEXT,
	"level"	TEXT,
	"level_id"	TEXT
	);

-- table: assembly_parts
CREATE TABLE "assembly_parts" (
	`assembly_no`	INTEGER,
	`part_no`	INTEGER,
	`l_village`	TEXT,
	`e_village`	TEXT,
	`l_assembly_name`	TEXT,
	`e_assembly_name`	TEXT,
	`l_list_description`	TEXT,
	`e_list_description`	TEXT,
	`date_published`	TEXT,
	`idversion`	INTEGER,
	`dataversion`	INTEGER,
	`photoversion`	INTEGER,
	`selected`	INTEGER,
	PRIMARY KEY(assembly_no,part_no)
);

-- table: cast_master
CREATE TABLE "cast_master" (
	`l_cast_name`	TEXT,
	`e_cast_name`	TEXT
);

-- table: color
CREATE TABLE "color" (
	`color`	TEXT,
	`local_description`	TEXT,
	`english_description`	TEXT,
	`hindi_description`	TEXT
);

-- table: daily_report
CREATE TABLE "daily_report" (
	"assembly_no"	INTEGER,
	"part_no"	INTEGER,
	"date_time"	TEXT,
	"is_saved"	INTEGER,
	"count_l_newaddress"	TEXT,
	"count_e_newaddress"	TEXT,
	"count_dead"	TEXT,
	"count_addresschange"	TEXT,
	"count_important"	TEXT,
	"count_color"	TEXT,
	"count_voted"	TEXT,
	"count_dob"	date,
	"count_mobile_no1"	TEXT,
	"count_mobile_no2"	TEXT,
	"count_emailid"	TEXT,
	"count_l_cast_name"	TEXT,
	"count_e_cast_name"	TEXT,
	"count_l_profession_name"	TEXT,
	"count_e_profession_name"	TEXT,
	"count_demands"	TEXT,
	"count_society"	TEXT,
	"count_flat_no"	TEXT,
	"count_extra_info1"	TEXT,
	"count_extra_info2"	TEXT,
	"count_extra_check1"	TEXT,
	"count_extra_check2"	TEXT,
	"count_extra_info3"	TEXT,
	"count_extra_info4"	TEXT,
	"count_extra_info5"	TEXT,
	"count_printed"	TEXT,
	"count_total"	TEXT,
	"count_supporter"	TEXT,
	"count_volunteer"	TEXT,
	"count_designator"	TEXT,
	"id"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);

-- table: labels
CREATE TABLE "labels" (
	`keyy`	TEXT,
	`local_label`	TEXT,
	`hindi_label`	TEXT,
	`english_label`	TEXT
);

-- table: languages
CREATE TABLE "languages" (
	`name`	TEXT,
	`description`	TEXT,
	`prefix`	TEXT,
	`selected`	INTEGER
);

-- table: memberinfo
CREATE TABLE "memberinfo" (
	`l_membername`	TEXT,
	`e_membername`	TEXT,
	`photo`	TEXT,
	`l_partyname`	TEXT,
	`e_partyname`	TEXT,
	`l_symbol`	TEXT,
	`e_symbol`	TEXT,
	`l_message`	TEXT,
	`e_message`	TEXT
);

-- table: new_voters
CREATE TABLE "new_voters" (
	`id`	TEXT,
	`name`	TEXT,
	`village`	TEXT,
	`address`	TEXT,
	`mobile_no`	TEXT,
	`dob`	TEXT,
	`remark`	TEXT
);

-- table: profession_master
CREATE TABLE `profession_master` (
'l_profession_name'	TEXT,
'e_profession_name'	TEXT
);

-- table: temp_voters
CREATE TABLE "temp_voters"(     "id" INTEGER PRIMARY KEY  ,      "assembly_no" INTEGER  ,      "part_no" INTEGER  ,      "srno" INTEGER  ,      "boothid" INTEGER  ,      "draft_srno" INTEGER  ,      "l_last_name" TEXT  ,      "l_first_name" TEXT  ,      "l_middle_name" TEXT  ,      "e_last_name" TEXT  ,      "e_first_name" TEXT  ,      "e_middle_name" TEXT  ,      "sex" TEXT  ,      "age" INTEGER  ,      "vcardid" TEXT  ,      "house_no" TEXT  ,      "l_village" TEXT  ,      "e_village" TEXT  ,      "l_taluka" TEXT  ,      "e_taluka" TEXT  ,      "l_assemblyname" TEXT  ,      "e_assemblyname" TEXT  ,      "l_address" TEXT  ,      "e_address" TEXT  ,      "booth_no" INTEGER  ,      "l_boothaddress" TEXT  ,      "e_boothaddress" TEXT  ,      "l_newaddress" TEXT  ,      "e_newaddress" TEXT  ,      "repeated" TEXT  ,      "repeated_no" TEXT  ,      "dead" TEXT  ,      "type" TEXT  ,      "vtype" TEXT  ,      "addresschange" TEXT  ,      "familyid" INTEGER  ,      "karykartano" INTEGER  ,      "important" TEXT  ,      "color" TEXT  ,      "voted" TEXT  ,      "dob" date  ,      "mobile_no1" TEXT  ,      "mobile_no2" TEXT  ,      "emailid" TEXT  ,      "l_cast_name" TEXT  ,      "e_cast_name" TEXT  ,      "l_profession_name" TEXT  ,      "e_profession_name" TEXT  ,      "demands" TEXT  ,      "society" TEXT  ,      "flat_no" TEXT  ,      "extra_info1" TEXT  ,      "extra_info2" TEXT  ,      "extra_check1" TEXT  ,      "extra_check2" TEXT  ,      "l_gat" TEXT  ,      "e_gat" TEXT  ,      "l_gan" TEXT  ,      "e_gan" TEXT  ,      "assembly_mapping" TEXT  ,      "full_name" TEXT  ,      "karyakarta1" TEXT  ,      "extra_info3" TEXT  ,      "extra_info4" TEXT  ,      "extra_info5" TEXT  ,      "printed" Text  );

-- table: voters
CREATE TABLE "voters" (
	"id"	INTEGER,
	"assembly_no"	INTEGER,
	"part_no"	INTEGER,
	"srno"	INTEGER,
	"boothid"	INTEGER,
	"draft_srno"	INTEGER,
	"l_last_name"	TEXT,
	"l_first_name"	TEXT,
	"l_middle_name"	TEXT,
	"e_last_name"	TEXT,
	"e_first_name"	TEXT,
	"e_middle_name"	TEXT,
	"sex"	TEXT,
	"age"	INTEGER,
	"vcardid"	TEXT,
	"house_no"	TEXT,
	"l_village"	TEXT,
	"e_village"	TEXT,
	"l_taluka"	TEXT,
	"e_taluka"	TEXT,
	"l_assemblyname"	TEXT,
	"e_assemblyname"	TEXT,
	"l_address"	TEXT,
	"e_address"	TEXT,
	"booth_no"	INTEGER,
	"l_boothaddress"	TEXT,
	"e_boothaddress"	TEXT,
	"l_newaddress"	TEXT,
	"e_newaddress"	TEXT,
	"repeated"	TEXT,
	"repeated_no"	TEXT,
	"dead"	TEXT,
	"type"	TEXT,
	"vtype"	TEXT,
	"addresschange"	TEXT,
	"familyid"	INTEGER,
	"karykartano"	INTEGER,
	"important"	TEXT,
	"color"	TEXT,
	"voted"	TEXT,
	"dob"	date,
	"mobile_no1"	TEXT,
	"mobile_no2"	TEXT,
	"emailid"	TEXT,
	"l_cast_name"	TEXT,
	"e_cast_name"	TEXT,
	"l_profession_name"	TEXT,
	"e_profession_name"	TEXT,
	"demands"	TEXT,
	"society"	TEXT,
	"flat_no"	TEXT,
	"extra_info1"	TEXT,
	"extra_info2"	TEXT,
	"extra_check1"	TEXT,
	"extra_check2"	TEXT,
	"l_gat"	TEXT,
	"e_gat"	TEXT,
	"l_gan"	TEXT,
	"e_gan"	TEXT,
	"assembly_mapping"	TEXT,
	"full_name"	TEXT,
	"karyakarta1"	TEXT,
	"extra_info3"	TEXT,
	"extra_info4"	TEXT,
	"extra_info5"	TEXT,
	"printed"	TEXT,
	"printed_by"	TEXT,
	"voted_by"	TEXT,
	PRIMARY KEY("id")
);

-- index: familyid
CREATE INDEX `familyid` ON `voters` (`familyid`);

-- index: full_name
CREATE INDEX `full_name` ON `voters` (`full_name`);

-- index: id
CREATE INDEX `id` ON `voters` (`id` ASC);

-- index: name
CREATE INDEX `name` ON `voters` (`e_last_name` ASC,`e_first_name` ASC,`e_middle_name` ASC);

-- index: part_no
CREATE INDEX `part_no` ON `voters` (`part_no` );

-- index: srno
CREATE INDEX `srno` ON `voters` (`srno` ASC);

-- index: vcard
CREATE INDEX `vcard` ON `voters` (`vcardid`);

