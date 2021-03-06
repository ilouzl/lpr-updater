from numpy import fromfile
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
import pandas_gbq

def load_from_gbq():
    scopes=[
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/bigquery",
        ]
    credentials = service_account.Credentials.from_service_account_file(
        'service-account.json', scopes=scopes)
    sql = "SELECT * FROM `lpr-leshem.lpr_form_requests.form_requests_spreadsheet`"
    df = pandas_gbq.read_gbq(sql, credentials=credentials)
    df.rename(columns=df.loc[0].to_dict(), inplace=True)
    df.drop(index=0, inplace=True)
    return df

def parse_ts(s):
    return datetime.strptime(s, "%d/%m/%Y %H:%M:%S")

def load_inquiries(fromfile=None):
    if fromfile is None:
        df = load_from_gbq()
    else:
        df = pd.read_csv(fromfile)
    # english column names
    columns_mapping = {'חותמת זמן':"ts",
                       'כתובת אימייל':"email", 
                       'שם משפחה':"surname",
                       'רחוב': "street",
                       'מספר בית': "home_number",
                       'מספר דירה': "apt_number",
                       'האם הנך רשומ/ה למערכת?': "is_registered",
                       'מה ברצונך לעשות?': "action",
                       'מספר רכב להסרה': "car_id_to_be_replaced",
                       'מספר רכב חדש': "car_id_to_replace",
                       'מספר רכב להסרה.1': "car_id_to_remove",
                       'בעל/ת הרכב (שם פרטי)': "name",
                       'ת״ז': "id",
                       'מספר רכב': "car_id",
                       'מעוניין להזין רכב נוסף?': "another_car",
                       'בעל/ת הרכב (שם פרטי).1': "name_2",
                       'ת״ז.1': "id_2",
                       'מספר רכב.1': "car_id_2"}
    # df = df.rename(columns=columns_mapping)
    df.columns = list(columns_mapping.values())
    df = df.dropna(how='all').reset_index(drop=True)
    
    df.ts = df.ts.apply(parse_ts)
    df.sort_values(by='ts', inplace=True, ignore_index=True)
    
    for c in ["apt_number", "car_id_to_be_replaced", "car_id_to_replace", 
                "car_id_to_remove", "id", "car_id", "id_2", "car_id_2"]:
        df[c] = df[c].astype('Int64')
    return df

def process_raw_cars_db(df):
    first_car = df.drop(columns = ["another_car", "name_2", "id_2", "car_id_2"])
    second_car = df[df.another_car=="כן"].drop(columns = ["another_car", "name", "id", "car_id"]).rename(columns={"name_2":"name", "id_2":"id", "car_id_2":"car_id"})
    all_cars = pd.concat([first_car, second_car], ignore_index=True)
    
    all_cars = format_names(all_cars)
    
    all_cars = all_cars.sort_values("id")
    all_cars = all_cars.drop_duplicates(subset=["car_id"])
    
    return all_cars

def export_to_lpr_format(cars_db):
    output = cars_db.sort_values("surname")
    output['full_name'] = output.apply(lambda r: r['name'] + " " + r['surname'], axis=1)
    output[['car_id','name','surname', 'full_name']].to_csv("out.csv", index=None)
    

def format_names(df):
    # remove unintentional spaces
    df.surname = df.surname.apply(lambda r: r.rstrip(" ").lstrip(" "))
    df.name = df.name.apply(lambda r: r.rstrip(" ").lstrip(" "))
    # remove surname from name field
    df.name = df.apply(lambda r: r["name"].replace(" " + r.surname, ""), axis=1) 
    return df
    
def handle_request(req, db):
    if "is_registered" in req.index:
        if req.is_registered == 'לא/לא יודע':
            db = handle_add_new_cars(req, db)
        elif req.is_registered == 'כן':
            if req.action == 'להחליף רכב קיים ברכב חדש':
                db = handle_replace_car(req, db)
            elif req.action == 'להוסיף רכב שני למשפחה':
                db = handle_add_second_car(req, db)
            elif req.action == 'להסיר רכב קיים':
                db = handle_remove_car(req, db)
    else:
        print("shouldn't get here")
        db = handle_add_new_cars_legacy(req, db)
    
    return db

def handle_add_new_cars_legacy(req, db):
    cars = req.drop(labels = ["another_car", "name_2", "id_2", "car_id_2"]).to_frame().T
    db = add_car(cars, db)
    if req.another_car=="כן":
        car2 = req.drop(labels = ["another_car", "name", "id", "car_id"]).rename({"name_2":"name", "id_2":"id", "car_id_2":"car_id"}).to_frame().T
        # cars = pd.concat([cars, car2])
        db = add_car(car2, db)
    
    # db = db.append(cars, ignore_index=True)
    return db

def handle_add_new_cars(req, db):
    req = req.drop(labels = ["is_registered", "action", "car_id_to_be_replaced", "car_id_to_replace", "car_id_to_remove"])
    return handle_add_new_cars_legacy(req, db)

def handle_add_second_car(req, db):
    req = req.drop(labels = ["is_registered", "action", "car_id_to_be_replaced", "car_id_to_replace", "car_id_to_remove"])
    req = req.drop(labels = ["another_car", "name", "id", "car_id"]).rename({"name_2":"name", "id_2":"id", "car_id_2":"car_id"}).to_frame().T
    db = add_car(req, db)
    return db

def add_car(car, db):
    if len(find_car_idx(car.car_id.values[0], db)) > 0:
        print("car %d already exists" % car.car_id.values[0])
    else:
        db = pd.concat([db, car], ignore_index=True)
    return db

def handle_replace_car(req, db):
    idx = find_car_idx(req.car_id_to_be_replaced, db)
    if idx is not []:
        db.loc[idx, "car_id"] = req.car_id_to_replace
    return db

def handle_remove_car(req, db):
    idx = find_car_idx(req.car_id_to_remove, db)
    if idx is not []:
        db = db.drop(index=idx).reset_index(drop=True)
    return db

def find_car_idx(car_id, db):
    idx = db.index[db.car_id == car_id].values
    if len(idx) == 1:
        return idx
    if len(idx) == 0:
        # print("car %d not found" % car_id)
        pass
    if len(idx) > 1:
        print("car %d not unique" % car_id)
        pass
    return []

# populate cars db
car_db = pd.DataFrame({"ts": [], "email": [], "surname": [], "street": [], 
                        "home_number":[],  "apt_number":[], "name":[],
                         "id": [], "car_id": []})
inq = load_inquiries()
for i, row in inq.iterrows():
    car_db = handle_request(row, car_db)

##### REPORTS #####

# more than two cars
family_groups = car_db.groupby(["surname", "street", "home_number"])
p = (family_groups.count() > 2).any(axis=1).values
family_list = list(family_groups.groups)
pd.concat([family_groups.get_group(family_list[i]) for i in range(len(p)) if p[i]]).to_csv("review_too_much_cars.csv", index=None)

# new families
reference_date = datetime(2022, 5, 1)
fam_ts = family_groups.ts.apply(min)
fam_ts[fam_ts > pd.Timestamp(reference_date)].to_csv("review_new_families.csv")

# cars list to lpr system
export_to_lpr_format(car_db)

