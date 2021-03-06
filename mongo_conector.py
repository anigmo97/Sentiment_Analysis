# encoding: utf-8
from pymongo import MongoClient,errors,ASCENDING,DESCENDING
from pymongo.collation import Collation
from bson.objectid import ObjectId
# from global_functions import change_dot_in_keys_for_bullet,change_bullet_in_keys_for_dot
import traceback
import json
import ast # to load query string to dict
from datetime import datetime
import re
from bson.code import Code
from deprecated import deprecated

MONGO_HOST= 'mongodb://localhost/tweet'
client = MongoClient(MONGO_HOST)
db = client.twitterdb

current_collection = "tweets"
default_collection = "tweets"

###################### SPECIAL DOCS #######################################################
statistics_file_id = "statistics_file_id"
query_file_id = "query_file_id"
streamming_file_id = "streamming_file_id"
searched_users_file_id = "searched_users_file_id"
likes_list_file_id = "likes_list_file_id" #deprecated
likes_count_file_id = "likes_count_file" #multiple files (particioned)
tweet_of_searched_users_not_captured_yet_file_id = "tweet_of_searched_users_not_captured_yet_file_id" # it's created in likes process in loop

special_doc_ids = [statistics_file_id,query_file_id,streamming_file_id,searched_users_file_id,likes_list_file_id,likes_count_file_id,tweet_of_searched_users_not_captured_yet_file_id]


########################### FIELDS ADDED TO TWEETS #######################################
def get_additional_tweet_fields():
    """Returns a dict with fields to set in a tweet before insert it"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    aux = {}
    aux["first_capture"] = now
    aux["last_update"] = now
    aux["has_likes_info"] = False
    return aux

def get_likes_info_registry(tweet_id,users_who_liked_dict,num_likes,author_screen_name,author_id):
    aux = {
        "tweet_id" : tweet_id,
        "users_who_liked" : users_who_liked_dict,
        "num_likes_capturados" : len(users_who_liked_dict),
        "num_likes" : num_likes,
        "last_like_resgistered" : str(datetime.now()),
        "veces_recorrido" : 1,
        "user_screen_name" : author_screen_name,
        "user_id" : author_id,
        "likes_count_updated":False
        }
    return aux

def get_tmp_likes_file_dict(tweet_id,likes_info_registry):
    if tweet_id.endswith("_tmp"):
        tweet_id = tweet_id[-4]
    aux = {
        "_id":tweet_id+"_tmp",
        "id_str":tweet_id+"_tmp",
        "has_likes_info" : True, 
        "likes_info":likes_info_registry , 
        "last_update": "--", 
        "created_at":"--",
        "user":{
            "screen_name":likes_info_registry["user_screen_name"]
            }
        }
    return aux
               



##########################################################################################
##################################### AUXILIAR ###########################################
##########################################################################################
def replace_bullet_with_dot(word):
    """Returns the string given replacing '•' for '.' """
    return word.replace('•','.')

def replace_dot_with_bullet(word):
    """Returns the string given replacing '.' for '•' """
    return word.replace('.','•') 

def change_dot_in_keys_for_bullet(dicctionary):
    """Returns a diccionary given replacing '.' in its keys for '•'\n
        This is necesarry to save the dict in mngo because mongo does not allow use keys with '.'"""
    new_dict = {}
    for k,v in dicctionary.items():
        if "." in k:
            print("[CHANGE DOT FOR BULLET INFO] Changing '.' in key {} for '•'".format(k))
            new_key = replace_dot_with_bullet(k)
            new_dict[new_key] = v
        else:
            new_dict[k] = v
    return new_dict

def change_bullet_in_keys_for_dot(dicctionary):
    """Returns a diccionary given replacing '•' in its keys for '.'"""
    new_dict = {}
    for k,v in dicctionary.items():
        if "•" in k:
            print("[CHANGE BULLET FOR DOT INFO] Changing '•' in key {} for '.'".format(k))
            new_key = replace_bullet_with_dot(k)
            new_dict[new_key] = v
        else:
            new_dict[k] = v
    return new_dict




#additional_function_pattern = re.compile(".*\)\.(\w+)\(.*")
##########################################################################################
##################################### GET INFO ###########################################
##########################################################################################


def get_count_of_a_collection(collection):
    """returns the num of doc (including special docs) from a collection"""
    return db[collection].count()

def get_likes_count_of_a_collection(collection):
    #TODO change
    mongo_cursor = db[collection].find({'_id':{"$regex":"^(?!likes_count_file)","$nin":special_doc_ids}})
    counter = 0
    for doc in mongo_cursor:
        likes_info = doc.get("likes_info",False)
        if likes_info:
            counter+= len(likes_info.get("users_who_liked",[]))
    return counter


def get_tweet_ids_list_from_database(collection):
    """returns a list with docs_ids (tweets_ids)\n
        Exclude special docs ids"""
    cursor_resultados = db[(collection or "tweets")].find({},{ "id_str": 1, "_id": 1 } )
    tweets_id_list = [x["id_str"] for x in cursor_resultados if x["_id"] not in special_doc_ids and not x["_id"].startswith("likes_count_file_id") ]
    return tweets_id_list

def get_tweet_ids_list_of_a_user_from_collection(user_id,collection):
    """Returns a list with docs_ids (tweets_ids) from a user given user_id and collection"""
    cursor_resultados = db[(collection or "tweets")].find({"user.id_str" : user_id},{ "id_str": 1, "_id": 1 } )
    tweets_id_list = [x["id_str"] for x in cursor_resultados if x["_id"] not in special_doc_ids and not x["_id"].startswith("likes_count_file_id")]
    return tweets_id_list

def get_searched_user_id_with_screenname(user_screen_name):
    """Returns user_id if is a searched user or None"""
    users_file = get_searched_users_file(current_collection)
    user = users_file.get(user_screen_name,None)
    #print("[GET SEARCHED_USER_ID WITH SCREEN NAME INFO] user = {}".format(json.dumps(user,indent=4)))
    return user.get("user_id",None)

def get_users_of_a_political_party(political_party,collection):
    """Returns a list of users screen_names of users of a political party\n
        from the searched users file of a collection\n
        Acepted parties: ["PP","PSOE","PODEMOS","CIUDADANOS","COMPROMIS","VOX"]"""
    political_party = political_party.upper()
    if political_party=="CS":
        political_party="CIUDADANOS"
    searched_users_file = get_searched_users_file(collection)
    politics = []
    if searched_users_file != None:
        for k,v in searched_users_file.items():
            if k != "_id" and k!="total_captured_tweets":
                if v["partido"] == political_party:
                    politics.append(k)

    return politics
  

def get_tweets_cursor_from_mongo(collection):
    """Returns a cursor of all documents from a collection except special docs"""
    print("[MONGO GET CURSOR INFO] Coleccion = {}".format(collection))
    #TODO change
    return db[(collection or "tweets")].find({'_id':{"$regex":"^(?!likes_count_file)","$nin":special_doc_ids}})

def get_tweets_ids_that_are_already_in_the_database(tweet_ids_list,collection):
    """Given a docs_ids (tweets_ids) list and a collection returns a list with\n
        those ids that are in the collection already"""
    map(ObjectId,tweet_ids_list)
    cursor_resultados = db[collection].find({'_id': {'$in': tweet_ids_list}},{'_id':1})
    tweets_id_list = [x["_id"] for x in cursor_resultados]
    return tweets_id_list

def get_keys_of_special_file_except_doc_id(special_doc):
    """Returns a list with all keys of a dict except _id"""
    if special_doc !=None:
        aux = special_doc
        del aux["_id"]
        return aux.keys()
    else:
        return []

def get_collection_names():
    """Returns colletions names of the database"""
    return db.collection_names()


def get_user_screen_name_of_tweet_id(tweet_id,collection):
    """Given a tweet_id and a collection returns user screen_name of the author"""
    cursor_resultados = db[collection].find({"_id": tweet_id})
    return cursor_resultados[0]["user"]["screen_name"]

def get_users_screen_name_dict_of_tweet_ids(tweet_id_list,collection):
    """Given a list of docs_ids (tweets_ids):\n
       returns a dict[tweet_id] -> screen_name"""
    cursor_resultados = db[collection].find({'_id': {'$in': tweet_id_list}},{'_id':1,'user.screen_name':1})
    dict_tweet_user = {}
    for e in cursor_resultados:
        print(e)
        dict_tweet_user[e["_id"]] = e["user"]["screen_name"]
    print(dict_tweet_user)
    return dict_tweet_user

def get_last_n_tweets_of_a_user_in_a_collection(user_id,collection,num_tweets):
    """Given a user_id < a collection and a number of messages to retrieve\n
        returns a list with the last n tweets ids of a users"""
    cursor_tweets_id = db[collection].find({"user.id_str": user_id},{"_id":1}).sort("_id",DESCENDING).limit(num_tweets)
    lista_tweets_id = [x["_id"] for x in cursor_tweets_id]
    lista_tweets_id.reverse()
    return lista_tweets_id


def get_tweets_to_analyze_or_update_stats(collection,limit=0):
    """Returns a list of tweets from the collection that have its 'analyzed' field distinct than True.\n
        This method returns tweets not analyzed and tweets analyzed that has been updated"""
    #TODO change
    lista_tweets = list(db[collection].find({"analyzed" :{"$ne": True}, '_id': {'$nin': special_doc_ids , "$regex":"^(?!likes_count_file)",'$not':re.compile("_tmp$")}}).limit(limit))
    print("[TWEETS FOR ANALYZE] {} tweets retrieved".format(len(lista_tweets)))
    return lista_tweets

def get_tweets_to_count_likes(collection,limit=0):
    """Returns a list of tweets from the collection that have its 'likes_info.likes_count_updated' field set to False"""
    #TODO change
    lista_tweets = list(db[collection].find({"has_likes_info" : True,"likes_info.likes_count_updated":False ,'_id': {'$nin': special_doc_ids,"$regex":"^(?!likes_count_file)"}}).limit(limit))
    print("[TWEETS FOR COUNT LIKES] {} tweets retrieved".format(len(lista_tweets)))
    print("{}".format([x["_id"] for x in lista_tweets]))
    return lista_tweets


def get_tweet_owner_dict_data_of_tweet_ids(tweet_id_list,collection):
    """Given a tweets_ids list and a collection:\n
        returns a dict with tweets ids as keys and a dict as value.\n
        The inner dict can have multiple keys:\n
        ['user_screen_name', 'last_update', 'is_retweet', 'is_quote']
        ['retweeted_user_screen_name', 'retweeted_tweet_id', 'quoted_user_screen_name', 'quoted_tweet_id']"""
    cursor_resultados = db[collection].find({'_id': {'$in': tweet_id_list}},
    {'_id':1,'user.screen_name':1,
    'retweeted_status.user.id_str':1,'retweeted_status.user.screen_name':1,'retweeted_status.id_str':1,
    'quoted_status.user.id_str':1,'quoted_status.user.screen_name':1,'quoted_status.id_str':1,'last_update':1})
    dict_tweet_user = {}
    for e in cursor_resultados:
        #print(e)
        aux = {}
        aux["user_screen_name"] = e["user"]["screen_name"]
        aux["last_update"] = e["last_update"]
        aux["is_retweet"] = bool(e.get("retweeted_status",False)) or False
        if aux["is_retweet"]:
            aux["retweeted_user_screen_name"] = e["retweeted_status"]["user"]["screen_name"]
            aux["retweeted_tweet_id"] = e["retweeted_status"]["id_str"]
        aux["is_quote"] = bool(e.get("quoted_status",False)) or False
        if aux["is_quote"]:
            aux["quoted_user_screen_name"] = e["quoted_status"]["user"]["screen_name"]
            aux["quoted_tweet_id"] = e["quoted_status"]["id_str"]
        dict_tweet_user[e["_id"]] = aux

    #print(dict_tweet_user)
    return dict_tweet_user

def get_users_screen_name_dict_of_tweet_ids_for_tops_in_statistics_file(statistics_file,collection):
    """Given the statistics dict of a collection and a collection:\n
        Returns a dict[tweet_id] -> user screen_name for tweets in top:\n
        ["global_most_favs_tweets", "global_most_rt_tweets", "local_most_replied_tweets", "local_most_quoted_tweets"]"""
    top_10_name_lists = ["global_most_favs_tweets","global_most_rt_tweets","local_most_replied_tweets","local_most_quoted_tweets"]
    tweet_id_list = []
    for top_list in top_10_name_lists:
        for e in statistics_file[top_list]:
            tweet_id_list.append(e[0])

    return  get_users_screen_name_dict_of_tweet_ids(tweet_id_list,collection)

def get_tweet_list_by_tweet_id_using_regex(regex,collection):
    #TODO change
    """Given a regex and a collection, returns a list of tweets who id satisficies the regex"""
    return [ x for x in db[collection].find({'_id':{'$regex':regex, '$nin': special_doc_ids, "$regex":"^(?!likes_count_file)"}})]

def get_tweet_dict_by_tweet_id_using_regex(regex,collection):
    #TODO change
    """Given a regex and a collection, returns a dict of tweets who id satisficies the regex"""
    return  { x['_id'] : x for x in db[collection].find({'_id':{'$regex':regex, '$nin': special_doc_ids, "$regex":"^(?!likes_count_file)"}})}
    #return  { x['_id'] : x for x in db[collection].find({'_id':{'$regex':regex, '$nin': special_doc_ids}}) if x["_id"][:-4]!= "_tmp"}



def get_tweet_by_id(id_str,collection):
    """Returns one doc with this id"""
    return (db[collection].find_one({'_id':id_str}) or None)

def get_tweets_list_by_id(id_list,collection):
    """Returns one doc with this id"""
    return db[collection].find({'_id':{'$in':id_list}})

def get_tweets_dict_by_id(id_list,collection):
    """Returns one doc with this id"""
    return {x['_id'] :x  for x in db[collection].find({'_id':{'$in':id_list}})}



##########################################################################################
##################################### UPDATE   ###########################################
##########################################################################################

def update_many_tweets_dicts_in_mongo(tweets_list,collection):
    """ replace multiple docs in mongo"""
    # replaceOne
    # update_one
    # db.tweets.update_many(tweets_list) hace falta un filter y un update tal vez se pueda hacer
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for tweet in tweets_list:
        tweet_id = tweet["id_str"]
        tweet["last_update"] = now
        db[(collection or "tweets")].replace_one({"_id" : tweet_id },tweet)



##########################################################################################
##################################### INSERT   ###########################################
##########################################################################################


def insertar_multiples_tweets_en_mongo_v2(mongo_tweets_dict,mongo_tweets_ids_list,collection):
    """Inserts multiple tweets in mongo:\n
        If some doc in already in the collection, will be ignored
        Check if exists temp files with likes before insert"""
    def concat_tmp(x):
        return x+"_tmp"
    print("[MONGO INSERT MANY INFO] Inserting tweets in mongo Collection = '{}' ".format(collection))
    #TODO COMPROBAR EN EJECUCIONES POR QUERY QUE NO ESTÁN YA
    tweets_no_insertados = 0
    try:
        repited_tweet_ids = get_tweets_ids_that_are_already_in_the_database(mongo_tweets_ids_list,collection)
        for repeated_id in repited_tweet_ids:
            del mongo_tweets_dict[repeated_id]
            tweets_no_insertados +=1

        tweets_no_repetidos = mongo_tweets_dict.values()
        if len(tweets_no_repetidos) >0:
            for e in tweets_no_repetidos:
                for k,v in get_additional_tweet_fields().items(): # we add special fields like first capture
                    e[k] = v

            # insertamos los tweets en mongo
            db[(collection or "tweets")].insert_many(tweets_no_repetidos)
            # comprobamos si para alguno de los documentos insertados existia un temporal con likes
            nombres_ficheros_temporales = map(concat_tmp,mongo_tweets_dict.keys())
            result_cursor = get_tweets_list_by_id(list(nombres_ficheros_temporales),collection)
            for tmp in result_cursor:
                name_without_tmp = tmp["_id"][:-4]
                db[collection].update({'_id':name_without_tmp}, {'$set': {"likes_info":tmp["likes_info"],"has_likes_info":True}})
                db[collection].remove({'_id':tmp["_id"]})
        if tweets_no_insertados > 0:
            print("[MONGO INSERT MANY WARN] {} messages weren't inserted because they were already in the collection {}".format(tweets_no_insertados,collection))
    except errors.BulkWriteError as bwe:
        detalles = bwe.details
        for error in detalles["writeErrors"]:
            del error["op"]
        print("\n\n"+traceback.format_exc())
        print("[MONGO INSERT MANY ERROR] {}\n\n".format(bwe))
        print("[MONGO INSERT MANY ERROR] \n {}".format(json.dumps(detalles["writeErrors"],indent=4, sort_keys=True)))
        exit(1)
    except Exception as e:
        print("\n\n"+traceback.format_exc())
        print("[MONGO INSERT MANY ERROR] {}\n\n".format(e))
        exit(1)
    print("[MONGO INSERT MANY INFO] Finish sucessfully ")
    return tweets_no_repetidos


##########################################################################################
############################### SPECIAL DOCS MANAGEMENT ##################################
##########################################################################################

def get_num_of_captured_likes_for_user(screen_name,collection):
    cursor_resultados = db[collection].find({"user.screen_name": screen_name})
    likes_capturados = 0
    for e in cursor_resultados:
        if e["has_likes_info"]:
            likes_capturados+= len(e["likes_info"]["users_who_liked"])
    return likes_capturados


def do_additional_actions_for_statistics_file(statistics_dict,collection):
    """Do a preprocess to treat the keys with '.' """
    print("[MONGO STATISTICS INFO] Changing bullets for dots")
    way_of_send_with_keys_with_dots =  change_bullet_in_keys_for_dot(statistics_dict["way_of_send_counter"])
    statistics_dict["way_of_send_counter"] = way_of_send_with_keys_with_dots
    return statistics_dict

def get_log_dict_for_special_file_id(file_id):
    """Returns a dict with logs for special docs"""
    if file_id.startswith("likes_count_file_id"):
        file_id = "likes_count_file_id"
    aux = {
        statistics_file_id : { "upper_name" : "STATISTICS_FILE", "file_aux" :"Fichero de estadisticas" , "file_id" : statistics_file_id },
        query_file_id : { "upper_name" : "QUERY_FILE", "file_aux" :"Fichero de querys" , "file_id" : query_file_id },
        streamming_file_id : { "upper_name" : "STREAMMING_FILE", "file_aux" :"Fichero de busquedas por streamming" , "file_id" : streamming_file_id },
        searched_users_file_id : { "upper_name" : "SEARCHED_USERS_FILE", "file_aux" :"Fichero de usuarios buscados" , "file_id" : searched_users_file_id },
        likes_count_file_id : { "upper_name" : "LIKES_COUNT_FILE", "file_aux" :"Fichero de conteo de likes" , "file_id" : likes_count_file_id },
        likes_list_file_id : { "upper_name" : "LIKES_FILE", "file_aux" :"Fichero de likes" , "file_id" : likes_list_file_id },
        tweet_of_searched_users_not_captured_yet_file_id : { "upper_name" : "TWEETS_IDS_OF_SEARCHED_USER_NOT_CAPTURED_YET_FILE", "file_aux" :"Fichero de tweets id de usuarios buscados no capturados todavía" , "file_id" : tweet_of_searched_users_not_captured_yet_file_id }
        
    }
    return aux.get(file_id,None)

def _get_special_file(collection,file_id):
    """Reserved method that get an expecial file from a collection"""    
    e = get_log_dict_for_special_file_id(file_id)
    cursor_resultados = db[(collection or "tweets")].find({"_id": file_id})
    file_list = [ x for x in cursor_resultados]
    if len(file_list) >1:
        raise Exception('[MONGO {} ERROR] Hay mas de un fichero con _id igual al {}: _id = {}'.format(e["upper_name"],e["file_aux"],e["file_id"]))
    elif len(file_list) == 1:
        print("[MONGO {} INFO] {} correctamente recuperado para la colección {}".format(e["upper_name"],e["file_aux"],collection))
        retrieved_file = file_list[0]
        if e["file_id"] != statistics_file_id:
            return retrieved_file
        else:
            return do_additional_actions_for_statistics_file(retrieved_file,collection)
    else:
        print("[MONGO {} INFO] No hay {} para la colección {}".format(e["upper_name"],e["file_aux"],collection))
        return None

def get_statistics_file_from_collection(collection):
    """Returns statistics file of a collection"""
    return _get_special_file(collection,statistics_file_id)

def get_query_file(collection):
    """Returns query file of a collection"""
    return _get_special_file(collection,query_file_id)

def get_streamming_file(collection):
    """Returns streamming file of a collection"""
    return _get_special_file(collection,streamming_file_id)

def get_searched_users_file(collection):
    """Returns searched users file of a collection"""
    return _get_special_file(collection,searched_users_file_id)

def get_likes_list_file(collection):
    """Returns likes file of a collection"""
    return _get_special_file(collection,likes_list_file_id)

def get_likes_count_files(collection):
    """Returns likes count files of  collection"""
    cursor_resultados = db[(collection)].find({"_id": {"$regex":"^(likes_count_file)"}}).sort("_id",ASCENDING).collation(Collation(locale="es",numericOrdering=True))
    return [ x for x in cursor_resultados]

def get_tweet_of_searched_users_not_captured_yet_file(collection):
    """Returns a special file that contains tweets_ids of tweets of searched users not captured yet of acollection\n
        (is used in likes process with queues)"""
    return _get_special_file(collection,tweet_of_searched_users_not_captured_yet_file_id)

def delete_tweet_of_searched_users_not_captured_yet_file(collection):
    """Deletes a special file that contains tweets_ids of tweets of searched users not captured yet of acollection\n
        (is used in likes process with queues)"""
    db[collection].remove({"_id":tweet_of_searched_users_not_captured_yet_file_id})

def delete_statistics_file(collection):
    """Deletes statistics file"""
    db[collection].remove({"_id":statistics_file_id})

########################################################## INSERTS #########################################################

def insert_statistics_file_in_collection(statistics_dict,collection):
    """Inserts a statistics_dict in a collection"""
    statistics_dict["_id"] = statistics_file_id
    statistics_dict["ultima_modificación"] = str(datetime.now())
    way_of_send_with_keys_without_dots =  change_dot_in_keys_for_bullet(statistics_dict["way_of_send_counter"])
    statistics_dict["way_of_send_counter"] = way_of_send_with_keys_without_dots

    if get_statistics_file_from_collection(collection)!= None:
        print(len(get_statistics_file_from_collection(collection)))
    #input("insercion")
    if get_statistics_file_from_collection(collection) == None:
        print("[MONGO INSERT STATISTICS FILE INFO] Inserting new statistics file in collection {}".format(collection))
        db[collection].insert(statistics_dict)
        print("[MONGO INSERT STATISTICS FILE INFO] The statistics file has been save sucessfully")
    else:
        print("[MONGO INSERT STATISTICS FILE INFO] Replacing statistics file")
        db[collection].replace_one({"_id" : statistics_file_id },statistics_dict) 
        print("[MONGO INSERT STATISTICS FILE INFO] The statistics file has been replaced save sucessfully")


def create_new_common_management_special_doc_dict(captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,capture_type):
    """Creates a common dict for query_file, searched_user_files and streamming_file"""
    aux = {}
    aux["last_execution"] = str(datetime.now())
    aux["max_tweet_id"] = max_tweet_id
    aux["min_tweet_id"] = min_tweet_id
    aux["min_creation_date"] = min_creation_date
    aux["max_creation_date"] = max_creation_date
    aux["search_type"] = capture_type
    aux["captured_tweets"] = captured_tweets
    return aux

def update_common_management_special_doc_dict(dict_for_update,max_tweet_id,min_tweet_id,min_creation_date,max_creation_date,captured_tweets):
    """Updates a common dict for query_file, searched_user_files and streamming_file"""
    aux = dict_for_update
    aux["last_execution"] = str(datetime.now())
    aux["max_tweet_id"] = max(max_tweet_id,aux["max_tweet_id"])
    aux["min_tweet_id"] = min(min_tweet_id,aux["min_tweet_id"])
    aux["min_creation_date"] = min(str(min_creation_date),aux["min_creation_date"])
    aux["max_creation_date"] = max(str(max_creation_date),aux["max_creation_date"])
    aux["captured_tweets"] = aux["captured_tweets"]+captured_tweets
    return aux

def _insert_or_update_special_file(collection,captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,file_id,
            query=None,words=None,words_comprobation=None,user=None,user_id=None,user_name=None,partido=None):
    """Inserts an special file with common form (query_file, searched_user_files and streamming_file) in a collection """
    print("[INSERT OR UPDATE SPECIAL FILE INFO]")
    if file_id not in special_doc_ids  and not file_id.startswith("likes_count_file_id"):
        raise Exception("El id {} no está entre los ids especiales".format(file_id))
        # tal vez solo use 3 ids

    logs = get_log_dict_for_special_file_id(file_id)

    special_doc_dict = _get_special_file(collection,file_id)

    if special_doc_dict != None:
        print("[INSERT OR UPDATE {0} INFO] There is {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero = False
        special_doc_dict["total_captured_tweets"] = special_doc_dict["total_captured_tweets"] + captured_tweets
    else:
        print("[INSERT OR UPDATE {0} INFO] There is NO {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero =True
        special_doc_dict = {"_id" : file_id}
        special_doc_dict["total_captured_tweets"] = captured_tweets

    if file_id == query_file_id:
        if query not in special_doc_dict:
            print("[INSERT OR UPDATE {0} INFO] Query is not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
            aux = create_new_common_management_special_doc_dict(captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,"tweets captured by query")
            aux["query"] = query
            special_doc_dict[query]= aux
        else:
            print("[INSERT OR UPDATE {0} INFO] Query is in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
            aux = update_common_management_special_doc_dict(special_doc_dict[query],max_tweet_id,min_tweet_id,min_creation_date,max_creation_date,captured_tweets)
            special_doc_dict[query] = aux
    elif file_id == streamming_file_id:
        words_comprobation =",".join(sorted([i.lower() for i in words]))
        if words_comprobation not in special_doc_dict:
            print("[INSERT OR UPDATE {0} INFO] WordsComprobation are not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
            aux = create_new_common_management_special_doc_dict(captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,"tweets captured by streamming")
            aux["words"] = words
            aux["words_comprobation"] = words_comprobation
            special_doc_dict[words_comprobation]= aux
        else:
            print("[INSERT OR UPDATE {0} INFO] Words comprobation are in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
            aux = update_common_management_special_doc_dict(special_doc_dict[words_comprobation],max_tweet_id,min_tweet_id,min_creation_date,max_creation_date,captured_tweets)
            special_doc_dict[words_comprobation] = aux
    elif file_id == searched_users_file_id:
        if user not in special_doc_dict:
            print("[INSERT OR UPDATE {0} INFO] User not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
            aux = create_new_common_management_special_doc_dict(captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,"tweets captured by user")
            aux["user"] = user
            aux["user_id"] = user_id
            aux["partido"] = partido
            aux["user_name"] = user_name
            special_doc_dict[user]= aux
        else:
            print("[INSERT OR UPDATE {0} INFO] User is in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
            aux = update_common_management_special_doc_dict(special_doc_dict[user],max_tweet_id,min_tweet_id,min_creation_date,max_creation_date,captured_tweets)
            special_doc_dict[user] = aux
    else:
        raise Exception("El id {} no está entre los ids especiales".format(file_id))


    if nuevo_fichero:
        print("[MONGO INSERT {0} INFO] Inserting new {0}".format(logs["upper_name"]))
        db[collection].insert(special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been save sucessfully".format(logs["upper_name"]))
    else:
        print("[MONGO INSERT {0} INFO] Replacing {0}".format(logs["upper_name"]))
        db[collection].replace_one({"_id" : file_id },special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been replaced and save sucessfully".format(logs["upper_name"]))
    


def insert_or_update_query_file(collection, query,captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date ):
    """Inserts query file in a collection"""
    _insert_or_update_special_file(collection=collection,captured_tweets=captured_tweets, min_tweet_id=min_tweet_id, max_tweet_id=max_tweet_id,min_creation_date = min_creation_date, max_creation_date=max_creation_date,
     file_id=query_file_id,query=query)
         

def insert_or_update_query_file_streamming(collection, words_list ,captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date ):
    """Inserts streamming file in a collection"""
    _insert_or_update_special_file(collection=collection,captured_tweets=captured_tweets, min_tweet_id=min_tweet_id, max_tweet_id=max_tweet_id,min_creation_date = min_creation_date, max_creation_date=max_creation_date,
     file_id=streamming_file_id,words=words_list)
    


def insert_or_update_searched_users_file(collection, user,user_id,user_name,captured_tweets, min_tweet_id, max_tweet_id, min_creation_date, max_creation_date,partido):
    """Inserts searched users file in a collection"""
    user= user.lower()
    _insert_or_update_special_file(collection=collection,captured_tweets=captured_tweets, min_tweet_id=min_tweet_id, max_tweet_id=max_tweet_id,min_creation_date = min_creation_date, max_creation_date=max_creation_date,
     file_id=searched_users_file_id,user=user,user_id=user_id,user_name=user_name,partido=partido)


def insert_or_update_likes_count_files(collection,user_id, user_screen_name,likes_to_PP,likes_to_PSOE,likes_to_PODEMOS,likes_to_CIUDADANOS,likes_to_VOX,likes_to_COMPROMIS,tweet_id):
    """Inserts users file in a collection"""
    logs = get_log_dict_for_special_file_id(likes_count_file_id)

    likes_count_files = get_likes_count_files(collection)
    print("LEN ={}".format(len(likes_count_files)))
    for e in likes_count_files:
        print("ID {} LENGTH {}".format(e["_id"],len(e)))
    special_doc_dict = None

    for e in likes_count_files:
        if user_id in e:
            special_doc_dict=e
    nuevo_fichero = False
    #TODO comprobar en que fichero añadirlo
    if special_doc_dict != None:
        print("[INSERT OR UPDATE {0} INFO] There is {0} in collection {1}".format(logs["upper_name"],collection))
    else:
        print("[INSERT OR UPDATE {0} INFO] There is NO {0} in collection {1}".format(logs["upper_name"],collection))
        if len(likes_count_files)>0 and len(likes_count_files[-1])< 6000: #TODO put 50001
            special_doc_dict = likes_count_files[-1]
        else:
            special_doc_dict = { "_id" : "likes_count_file_id_" + str(len(likes_count_files))}
            nuevo_fichero =True
        

    if user_id not in special_doc_dict:
        print("[INSERT OR UPDATE {0} INFO] Query is not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
        aux = {}
        aux["user_id"] = user_id
        aux["user_screen_name"] = user_screen_name
        aux["likes_to_PP"] = (likes_to_PP or 0)
        aux["likes_to_PSOE"] = (likes_to_PSOE or 0)
        aux["likes_to_PODEMOS"] = (likes_to_PODEMOS or 0)
        aux["likes_to_CIUDADANOS"] = (likes_to_CIUDADANOS or 0)
        aux["likes_to_VOX"] = (likes_to_VOX or 0)
        aux["likes_to_COMPROMIS"] = (likes_to_COMPROMIS or 0)
        aux["last_like_registered"] = str(datetime.now())
        aux["tweet_ids_liked_list"] =[tweet_id]
        special_doc_dict[user_id]= aux
    else:
        print("[INSERT OR UPDATE {0} INFO] Query is in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
        aux = special_doc_dict[user_id]
        aux["likes_to_PP"] = aux["likes_to_PP"] + (likes_to_PP or 0)
        aux["likes_to_PSOE"] = aux["likes_to_PSOE"] + (likes_to_PSOE or 0)
        aux["likes_to_PODEMOS"] = aux["likes_to_PODEMOS"] + (likes_to_PODEMOS or 0)
        aux["likes_to_CIUDADANOS"] = aux["likes_to_CIUDADANOS"] + (likes_to_CIUDADANOS or 0)
        aux["likes_to_VOX"] = aux["likes_to_VOX"] + (likes_to_VOX or 0)
        aux["likes_to_COMPROMIS"] = aux["likes_to_COMPROMIS"] + (likes_to_COMPROMIS or 0)
        aux["last_like_registered"] = str(datetime.now())
        aux["tweet_ids_liked_list"].append(tweet_id)
        special_doc_dict[user_id] = aux


    if nuevo_fichero:
        print("[MONGO INSERT {0} INFO] Inserting new {0}".format(logs["upper_name"]))
        db[collection].insert(special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been save sucessfully".format(logs["upper_name"]))
    else:
        print("[MONGO INSERT {0} INFO] Replacing {0}".format(logs["upper_name"]))
        db[collection].replace_one({"_id" : special_doc_dict["_id"] },special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been replaced and save sucessfully".format(logs["upper_name"]))
    
def replace_likes_count_file(collection,likes_count_file):
    db[collection].replace_one({"_id" : likes_count_file["_id"] },likes_count_file,upsert=True)

def replace_searched_users_file(collection,new_file):
    db[collection].replace_one({"_id" : searched_users_file_id },new_file,upsert=True)
    


def insert_tweet_of_searched_users_not_captured_yet_file(special_doc_dict,collection):
    try:
        db[collection].insert({"_id" : tweet_of_searched_users_not_captured_yet_file_id },special_doc_dict,upsert=True)
    except:
        db[collection].replace_one({"_id" : tweet_of_searched_users_not_captured_yet_file_id },special_doc_dict,upsert=True)


def get_user_who_liked_dict_merge(dict_1,dict_2):
    merged_dict = dict_1.copy()
    new_likes = 0
    for k,v in dict_2.items():
        if k not in dict_1:
            merged_dict[k] =v 
            new_likes +=1
    return merged_dict,new_likes

def insert_or_update_likes_info_in_docs(tweet_likes_info_dict,collection):
    def concat_tmp(x):
        return x+"_tmp"

    ids_that_are_in_database = get_tweets_dict_by_id(list(tweet_likes_info_dict.keys()),collection)
    nombres_ficheros_temporales = list(map(concat_tmp,tweet_likes_info_dict.keys()))
    tmp_ids_that_are_in_database = get_tweets_dict_by_id(nombres_ficheros_temporales,collection)

    for tweet,likes_info_to_insert in tweet_likes_info_dict.items():
        aux = likes_info_to_insert.copy()
        if tweet in ids_that_are_in_database:
            if ids_that_are_in_database[tweet]["has_likes_info"]:
                likes_info_from_collection =  ids_that_are_in_database[tweet]["likes_info"]   
                users_who_liked_aux, new_likes = get_user_who_liked_dict_merge(likes_info_from_collection["users_who_liked"],likes_info_to_insert["users_who_liked"])    
                aux["users_who_liked"] = users_who_liked_aux
                aux["veces_recorrido"] = likes_info_from_collection.get("veces_recorrido",8) +1
            aux["num_likes_capturados"] = len(aux["users_who_liked"])
            db[collection].update({'_id':tweet}, {'$set': {"likes_info":aux}})
        else:
            tweet_id_tmp = tweet+"_tmp"
            if tweet_id_tmp in tmp_ids_that_are_in_database:
                likes_info_from_collection =  tmp_ids_that_are_in_database[tweet_id_tmp]["likes_info"] 
                users_who_liked_aux,new_likes = get_user_who_liked_dict_merge(likes_info_from_collection["users_who_liked"],likes_info_to_insert["users_who_liked"])
                aux["users_who_liked"] = users_who_liked_aux   
                aux["num_likes_capturados"] = len(aux["users_who_liked"])
                aux["veces_recorrido"] = likes_info_from_collection["veces_recorrido"] +1
                db[collection].update({'_id':tweet_id_tmp}, {'$set': {"likes_info":aux}})   
            else:
                try:
                    db[collection].insert(get_tmp_likes_file_dict(tweet,aux))
                except Exception as e:
                    print(e)
                        

def insert_or_update_one_registry_of_likes_list_file_v2(collection,tweet_id,num_likes,users_who_liked_dict,author_id,author_screen_name,tupla_likes):
    tweet_dict = get_tweet_by_id(tweet_id,collection)
    tweet_tmp_dict = get_tweet_by_id(tweet_id+"_tmp",collection)
    new_likes=0
    aux = get_likes_info_registry(tweet_id,users_who_liked_dict,num_likes,author_screen_name,author_id)

    if tweet_dict !=None: # if the tweet is already in the collection
        if tweet_dict.get("has_likes_info",False):
            users_who_liked_aux,new_likes = get_user_who_liked_dict_merge(tweet_dict["likes_info"]["users_who_liked"],aux["users_who_liked_dict"])    
            aux["users_who_liked"] = users_who_liked_aux
            aux["num_likes_capturados"] = len(aux["users_who_liked"])
            aux["veces_recorrido"] = tweet_dict["likes_info"]["veces_recorrido"] +1
        db[collection].update({'_id':tweet_id}, {'$set': {"likes_info":aux, "has_likes_info":True}})
    else:
        if tweet_tmp_dict != None: # the tmp is not in the collection
            users_who_liked_aux,new_likes = get_user_who_liked_dict_merge(tweet_tmp_dict["likes_info"]["users_who_liked"],aux["users_who_liked_dict"])
            aux["users_who_liked"] = users_who_liked_aux
            aux["num_likes_capturados"] = len(aux["users_who_liked"]) 
            aux["veces_recorrido"] = tweet_tmp_dict["veces_recorrido"] +1
            db[collection].update({'_id':tweet_id+"_tmp"}, {'$set': {"likes_info":aux,"has_likes_info":True}})   
        else:
            try:
                db[collection].insert(get_tmp_likes_file_dict(tweet_id,aux))
            except Exception as e:
                print(e)
    return new_likes

        
def insert_likes_file_list_if_not_exists(collection):
    if get_likes_list_file(collection) == None:
        db[collection].insert({"_id":likes_list_file_id,"info":"likes file is deprecated, now each tweet stores its own likes info"})



def mark_docs_as_analyzed(docs_ids,collection):
    """Given a list of docs ids, sets its 'analyzed' field as True"""
    print("[mark_docs_as_analyzed] marking as analyzed {} tweets".format(len(docs_ids)))
    db[collection].update({'_id':{'$in': docs_ids}}, {'$set': {"analyzed":True}}, multi=True)

def mark_docs_as_not_analyzed(collection):
    """Sets 'analyzed' field as False in all documents of a collections except special docs,\n
        Removes Statistics Dict"""
    docs_ids = get_tweet_ids_list_from_database(collection)
    db[collection].update({'_id':{'$in': docs_ids}}, {'$set': {"analyzed":False}}, multi=True)
    print("[MONGO STATISTICS WARN] Deleting statistics file")
    db[collection].remove({"_id":statistics_file_id})
    print("[MONGO STATISTICS WARN] Statistics file has been deleted")

def mark_likes_as_not_counted(collection):
    """ Sets 'likes_info.likes_count_update' to false and puts all likes count to False and removes users_file"""
    #TODO: change
    db[collection].update({"likes_info" : {"$exists" : True}, '_id': {'$nin': special_doc_ids ,"$regex":"^(?!likes_count_file)"}},
        {'$set': {"has_likes_info":True,"likes_info.likes_count_updated":False}},multi=True)
    #TODO: change
    mongo_cursor = db[collection].find({"has_likes_info":True, '_id': {'$nin': special_doc_ids,"$regex":"^(?!likes_count_file)" }},{"_id": 1, "likes_info.users_who_liked":1})
    for e in mongo_cursor:
        doc_id = e["_id"]
        #print(e)
        users_who_liked = e["likes_info"]["users_who_liked"].copy()
        for i in users_who_liked:
             users_who_liked[i]["counted"] = False
        db[collection].update({"_id":doc_id},{"$set":{"likes_info.users_who_liked":users_who_liked}},multi=True)

    db[collection].remove({"_id":{"$regex":"^likes_count_file_id"}})

    

#mark_docs_as_not_analyzed("test2")






##################################################################################################################
######################################### DEPRECATED #############################################################
##################################################################################################################  


@deprecated(version='1.0', reason="Deprecated, It was used when a tweet couldn't be in a collection")
def insertar_multiples_tweets_en_mongo(mongo_tweets_dict,mongo_tweets_ids_list,collection):
    """Inserts multiple tweets in mongo:\n
        If some doc in already in the collection, will be ignored"""
    print("[MONGO INSERT MANY INFO] Inserting tweets in mongo Collection = '{}' ".format(collection))
    #TODO COMPROBAR EN EJECUCIONES POR QUERY QUE NO ESTÁN YA
    tweets_no_insertados = 0
    try:
        repited_tweet_ids = get_tweets_ids_that_are_already_in_the_database(mongo_tweets_ids_list,collection)
        for repeated_id in repited_tweet_ids:
            del mongo_tweets_dict[repeated_id]
            tweets_no_insertados +=1

        tweets_no_repetidos = mongo_tweets_dict.values()
        if len(tweets_no_repetidos) >0:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for e in tweets_no_repetidos:
                e["first_capture"] = now
                e["last_update"] = now
            db[(collection or "tweets")].insert_many(tweets_no_repetidos)
        if tweets_no_insertados > 0:
            print("[MONGO INSERT MANY WARN] {} messages weren't inserted because they were already in the collection {}".format(tweets_no_insertados,collection))
    except errors.BulkWriteError as bwe:
        detalles = bwe.details
        for error in detalles["writeErrors"]:
            del error["op"]
        print("\n\n"+traceback.format_exc())
        print("[MONGO INSERT MANY ERROR] {}\n\n".format(bwe))
        print("[MONGO INSERT MANY ERROR] \n {}".format(json.dumps(detalles["writeErrors"],indent=4, sort_keys=True)))
        exit(1)
    except Exception as e:
        print("\n\n"+traceback.format_exc())
        print("[MONGO INSERT MANY ERROR] {}\n\n".format(e))
        exit(1)
    print("[MONGO INSERT MANY INFO] Finish sucessfully ")
    return tweets_no_repetidos

@deprecated(version='1.0', reason="Deprecated, It was used in old likes file")
def insert_or_update_multiple_registries_of_likes_list_file(tweet_likes_info_dict,collection):
    """Deprecated, It was used in old likes file"""
    likes_list_file = get_likes_list_file(collection)
    new_file =True
    for tweet,tweet_info in tweet_likes_info_dict.items():
        aux = tweet_info.copy()
        if tweet in likes_list_file:
            aux["users_who_liked"] = likes_list_file[tweet]["users_who_liked"]
            for k,v in tweet_info["users_who_liked"].items():
                aux["users_who_liked"][k] =v
        aux["num_likes_capturados"] = len(aux["users_who_liked"])
        db[collection].update({'_id':likes_list_file_id}, {'$set': {tweet:aux}})

@deprecated(version='1.0', reason="Deprecated, It was used in old likes file")
def insert_or_update_one_registry_of_likes_list_file(collection,tweet_id,num_likes,users_who_liked_dict,author_id,author_screen_name,tupla_likes):
    """Deprecated DO NOT USE ,DOES A LOT OF WRITES"""
    logs = get_log_dict_for_special_file_id(likes_list_file_id)

    special_doc_dict = _get_special_file(collection,likes_list_file_id)
    likes_to_PP,likes_to_PSOE,likes_to_PODEMOS,likes_to_CIUDADANOS,likes_to_VOX,likes_to_COMPROMIS = tupla_likes

    if special_doc_dict != None:
        print("[INSERT OR UPDATE {0} INFO] There is {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero = False
    else:
        print("[INSERT OR UPDATE {0} INFO] There is NO {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero =True
        special_doc_dict = {"_id" : likes_list_file_id}

    if tweet_id not in special_doc_dict:
        print("[INSERT OR UPDATE {0} INFO] Query is not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
        aux = {}
        aux["tweet_id"] = tweet_id
        aux["user_id"] = author_id
        aux["user_screen_name"] = author_screen_name
        aux["users_who_liked"] = users_who_liked_dict
        for user_id,user_name,user_screen_name in users_who_liked_dict.values():
            insert_or_update_users_file(collection,user_id,user_screen_name,likes_to_PP,likes_to_PSOE,likes_to_PODEMOS,likes_to_CIUDADANOS,likes_to_VOX,likes_to_COMPROMIS,tweet_id)
        aux["num_likes"] = num_likes
        aux["last_like_resgistered"] = str(datetime.now())
        aux["num_likes_capturados"] = len(aux["users_who_liked"])
        aux["veces_recorrido"] = 1
        special_doc_dict[tweet_id]= aux
    else:
        print("[INSERT OR UPDATE {0} INFO] Query is in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
        aux = special_doc_dict[tweet_id]
        print(aux["users_who_liked"])
        for user_id,user_name,user_screen_name in users_who_liked_dict.values():
            if user_id not in aux["users_who_liked"]:
                aux["users_who_liked"][user_id] = (user_id,user_name,user_screen_name)
                insert_or_update_users_file(collection,user_id,user_screen_name,likes_to_PP,likes_to_PSOE,likes_to_PODEMOS,likes_to_CIUDADANOS,likes_to_VOX,likes_to_COMPROMIS,tweet_id)
        aux["num_likes"] = num_likes
        aux["num_likes_capturados"] = len(aux["users_who_liked"])
        aux["last_like_resgistered"] = str(datetime.now())
        aux["veces_recorrido"] = aux.get("veces_recorrido",1)+1
        special_doc_dict[tweet_id] = aux


    if nuevo_fichero:
        print("[MONGO INSERT {0} INFO] Inserting new {0}".format(logs["upper_name"]))
        db[collection].insert(special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been save sucessfully".format(logs["upper_name"]))
    else:
        print("[MONGO INSERT {0} INFO] Replacing {0}".format(logs["upper_name"]))
        db[collection].replace_one({"_id" : likes_list_file_id },special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been replaced and save sucessfully".format(logs["upper_name"]))
    
    return len(aux["users_who_liked"])

@deprecated(version='1.0', reason="Deprecated, It was used when likes cout were stored in only one file")
def get_users_file(collection):
    """Returns users file of a collection"""
    return _get_special_file(collection,likes_count_file_id)

@deprecated(version='1.0', reason="Deprecated, It was used when likes cout were stored in only one file")
def insert_or_update_users_file(collection,user_id, user_screen_name,likes_to_PP,likes_to_PSOE,likes_to_PODEMOS,likes_to_CIUDADANOS,likes_to_VOX,likes_to_COMPROMIS,tweet_id):
    """Inserts users file in a collection"""
    logs = get_log_dict_for_special_file_id(likes_count_file_id)

    special_doc_dict = _get_special_file(collection,likes_count_file_id)

    if special_doc_dict != None:
        print("[INSERT OR UPDATE {0} INFO] There is {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero = False
    else:
        print("[INSERT OR UPDATE {0} INFO] There is NO {0} in collection {1}".format(logs["upper_name"],collection))
        nuevo_fichero =True
        special_doc_dict = {"_id" : likes_count_file_id}

    if user_id not in special_doc_dict:
        print("[INSERT OR UPDATE {0} INFO] Query is not in {0} (collection {1}), adding new entry ...".format(logs["upper_name"],collection))
        aux = {}
        aux["user_id"] = user_id
        aux["user_screen_name"] = user_screen_name
        aux["likes_to_PP"] = (likes_to_PP or 0)
        aux["likes_to_PSOE"] = (likes_to_PSOE or 0)
        aux["likes_to_PODEMOS"] = (likes_to_PODEMOS or 0)
        aux["likes_to_CIUDADANOS"] = (likes_to_CIUDADANOS or 0)
        aux["likes_to_VOX"] = (likes_to_VOX or 0)
        aux["likes_to_COMPROMIS"] = (likes_to_COMPROMIS or 0)
        aux["last_like_registered"] = str(datetime.now())
        aux["tweet_ids_liked_list"] =[tweet_id]
        special_doc_dict[user_id]= aux
    else:
        print("[INSERT OR UPDATE {0} INFO] Query is in {0} already (collection {1}), updating entry ...".format(logs["upper_name"],collection))
        aux = special_doc_dict[user_id]
        aux["likes_to_PP"] = aux["likes_to_PP"] + (likes_to_PP or 0)
        aux["likes_to_PSOE"] = aux["likes_to_PSOE"] + (likes_to_PSOE or 0)
        aux["likes_to_PODEMOS"] = aux["likes_to_PODEMOS"] + (likes_to_PODEMOS or 0)
        aux["likes_to_CIUDADANOS"] = aux["likes_to_CIUDADANOS"] + (likes_to_CIUDADANOS or 0)
        aux["likes_to_VOX"] = aux["likes_to_VOX"] + (likes_to_VOX or 0)
        aux["likes_to_COMPROMIS"] = aux["likes_to_COMPROMIS"] + (likes_to_COMPROMIS or 0)
        aux["last_like_registered"] = str(datetime.now())
        aux["tweet_ids_liked_list"].append(tweet_id)
        special_doc_dict[user_id] = aux


    if nuevo_fichero:
        print("[MONGO INSERT {0} INFO] Inserting new {0}".format(logs["upper_name"]))
        db[collection].insert(special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been save sucessfully".format(logs["upper_name"]))
    else:
        print("[MONGO INSERT {0} INFO] Replacing {0}".format(logs["upper_name"]))
        db[collection].replace_one({"_id" : likes_count_file_id },special_doc_dict)
        print("[MONGO INSERT {0} INFO] The {0} has been replaced and save sucessfully".format(logs["upper_name"]))
    
