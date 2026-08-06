DROP TABLE IF EXISTS pdr_inventory.ehr_software_analysis;

CREATE EXTERNAL TABLE IF NOT EXISTS pdr_inventory.ehr_software_analysis (
    path                              STRING,
    filename                          STRING,
    qe                                STRING,
    input_assigning_authority         STRING,
    processing_time_ms                INT,
    file_size_bytes                   INT,
    assigning_authority_parsed_from_s3 STRING,
    oid                               STRING,
    software_name                     STRING,
    manufacturer_model_name           STRING,
    custodian_org_name                STRING,
    ehr_guess                         STRING,
    ehr_guess_confidence              STRING,
    ehr_guess_reason                  STRING,
    parse_type                        STRING,
    qe_aa                             STRING
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ',',
    'quoteChar'     = '"'
)
STORED AS TEXTFILE
LOCATION 's3://pdr-nyec-local/EPICHospitalAnalysis/'
TBLPROPERTIES (
    'skip.header.line.count' = '1'
)
