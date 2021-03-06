#import required packages
import os
import sys
from multiprocessing.dummy import Pool
import pandas as pd
import pycurl
import io
from io import BytesIO
import numpy as np
from boxsdk import JWTAuth, OAuth2, Client

cur_dir = os.path.dirname(os.path.abspath(__file__))
default_cache = "/data/intradb/tmp/box2nda_cache"  #cache for data

boxconfigfile="~/BoxApp.json" #where configuration file is for Box on local computer, should change depending on where you are running the code

#Making commands under a class to be called from main code
class LifespanBox:
    def __init__(self, cache=default_cache, user='Lifespan Automation'):
        self.user = user
        self.cache = cache
        if not os.path.exists(cache):
            os.mkdir(cache)
        self.client = self.get_client()

    def get_client(self):
        auth = JWTAuth.from_settings_file(boxconfigfile)
   
        # access_token = auth.authenticate_instance()
        admin_client = Client(auth)

        lifespan_user = None
        # lifespan_user = client.create_user('Lifespan Automation')
        for user in admin_client.users():
            if user.name == self.user:
                lifespan_user = user
                # print(lifespan_user.login)

        if not lifespan_user:
            print(self.user + ' user was not found. Exiting...')
            sys.exit(-1)

        return admin_client.as_user(lifespan_user)

    def get_dev_client(self):
        # Dev access token, active for 1 hour. Get new token here:
        # https://wustl.app.box.com/developers/console/app/333873/configuration
        auth = OAuth2(
            client_id='',
            client_secret='',
            access_token=''
        )
        return Client(auth)

    def folder_info(self, folder_id):
        f = self.client.folder(folder_id=str(folder_id)).get()
        print('folder owner: ' + f.owned_by['login'])
        print('folder name: ' + f['name'])

    def get_files(self, folder_id, pattern=None, maxfiles=None):
        """ Gets all files in a folder matching pattern up to maxfiles
        :pattern - Can be any string and can contain '*' for wildcards
        :maxfiles - May return slightly more than this due to the offset value
            and pattern matching
        """
        limit = 1000
        if maxfiles and maxfiles < limit:
            limit = maxfiles
        offset = 0
        root_folder = self.client.folder(folder_id=str(folder_id))
        files = []

        while True:
            items = root_folder.get_items(limit=limit, offset=offset)

            for f in items:
                if f.type != 'file':
                    continue
                if not pattern:
                    files.append(f)
                elif self._match(f.name, pattern):
                    files.append(f)

            # We either exhausted the listing or have reached maxfiles
            if not items:
                break
            if maxfiles and len(files) >= maxfiles:
                break

            offset += limit

        return files

    def search(self, pattern, limit=100, maxresults=1000, exclude=None,ancestor_folders=None,file_extensions=None):
        """
        Extends box search to narrow down based on glob like pattern
        Exclusions can be specified as comma separated string, like 'Not,This'
        """
        offset = 0
        results = []
        print('looking for "{}" ...'.format(pattern))
        result = self.client.search().query(pattern, limit=limit, offset=offset, ancestor_folders=ancestor_folders,file_extensions=file_extensions)
        results.extend(result)

        matches = []

        for r in results:
            match = True
            for substr in pattern.split('*'):
                if substr not in r.name:
                    match = False
            if match:  # and exclude and exclude not in r.name:
                if not exclude:
                    matches.append(r)
                else:
                    exclusions = exclude.split(',')
                    included = True
                    for exclusion in exclusions:
                        if exclusion in r.name:
                            included = False
                    if included:
                        matches.append(r)

        return matches

    def download_file(self, file_id):
        """
        Downloads a single file to cache space or provided directory
        """

        f = self.client.file(file_id=str(file_id))
        # print(dir(f))
        print(f.get().name)
        file_path = os.path.join(self.cache, f.get().name)

        with open(file_path, 'wb') as out:
           # out.write(f.content())
             f.download_to(out)

        return f

    def download_files(self, file_ids, directory=None, workers=20):
        """
        Takes a list of file ids and downloads them all to cache space or user
        specified directory
        """
        if directory:
            self.cache = directory
        pool = Pool(workers)
        pool.map(self.download_file, file_ids)
        pool.close()
        pool.join()
        # Euivalent to this for loop
        # for f in file_ids:
        #     self.download_file(f)

    def upload_file(self, source_path, folder_id):
         filename = os.path.basename(source_path)
         f = self.client.folder(str(folder_id)).upload(source_path)
         print(f)

    def update_file(self, file_id, file_path):
        f = self.client.file(str(file_id))
        f.update_contents(file_path)

    @staticmethod
    def _match(string, pattern):
        match = True
        for substr in pattern.split('*'):
            # Skip "empty" matches
            if not substr:
                continue

            if substr not in string:
                # print(substr)
                match = False
        return match



    def getredcapdata(self): #, token=token[0],field=field[0],event=event[0]):
        """
        Downloads required fields for all nda structures from Redcap databases specified by details in redcapconfig file
        Returns panda dataframe with fields 'study', 'Subject_ID, 'subject', and 'flagged', where 'Subject_ID' is the 
        patient id in the database of interest (sometimes called subject_id, parent_id). 
        subject is this same id stripped of underscores or flags like 'excluded' to make it easier to merge
        flagged contains the extra characters other than the id so you can keep track of who should NOT be uploaded to NDA
         or elsewwhere shared
        """
        auth = pd.read_csv(redcapconfigfile)
        studydata=pd.DataFrame()  
        #DONT skip 1st row of auth which holds parent info
        for i in range(0,len(auth.study)):
            data = {
                'token': auth.token[i],  'content': 'record','format': 'csv', 'type': 'flat',  'fields[0]': auth.field[i],
                'fields[1]': auth.interview_date[i],'fields[2]': auth.sexatbirth[i],'fields[3]': auth.sitenum[i],'fields[4]': auth.dobvar[i], 
                'events[0]': auth.event[i], 'rawOrLabel': 'raw', 'rawOrLabelHeaders': 'raw',    'exportCheckboxLabel': 'false',
                'exportSurveyFields': 'false', 'exportDataAccessGroups': 'false',   'returnFormat': 'json'  }
            buf = BytesIO()
            ch = pycurl.Curl()
            ch.setopt(ch.URL, 'https://redcap.wustl.edu/redcap/srvrs/prod_v3_1_0_001/redcap/api/')
            ch.setopt(ch.HTTPPOST, list(data.items()))
            ch.setopt(ch.WRITEDATA, buf)
            ch.perform()
            ch.close()
            htmlString = buf.getvalue().decode('UTF-8')
            buf.close()
            parent_ids=pd.DataFrame(htmlString.splitlines(),columns=['row'])
            header=parent_ids.iloc[0]
            headerv2=header.str.replace(auth.interview_date[i],'interview_date')
            headerv3=headerv2.str.split(',')
            parent_ids.drop([0],inplace=True)
            pexpanded=pd.DataFrame(parent_ids.row.str.split(pat=',').values.tolist(),columns=headerv3.values.tolist()[0])
            #pexpanded=pexpanded.loc[~(pexpanded.subject_id=='')]
            #new=pexpanded['subject_id'].str.split("_",1,expand=True)
            pexpanded=pexpanded.loc[~(pexpanded[auth.field[i]]=='')]
            new=pexpanded[auth.field[i]].str.split("_",1,expand=True)
            pexpanded['subject']=new[0].str.strip()
            pexpanded['flagged']=new[1].str.strip()
            pexpanded['study']=auth.study[i]
            studydata=pd.concat([studydata,pexpanded],axis=0,sort=True)
        return studydata


    def getredcapfields(self,fieldlist, study='hcpa'):  # , token=token[0],field=field[0],event=event[0]):
        """
        Downloads requested fields from Redcap databases specified by details in redcapconfig file
        Returns panda dataframe with fields 'study', 'Subject_ID, 'subject', and 'flagged', where 'Subject_ID' is the
        patient id in the database of interest (sometimes called subject_id, parent_id) as well as requested fields.
        subject is this same id stripped of underscores or flags like 'excluded' to make it easier to merge
        flagged contains the extra characters other than the id so you can keep track of who should NOT be uploaded to NDA
         or elsewwhere shared
        """
        auth = pd.read_csv(redcapconfigfile)
        studydata = pd.DataFrame()
        fieldlistlabel = ['fields[' + str(i) + ']' for i in range(5, len(fieldlist) + 5)]
        fieldrow = dict(zip(fieldlistlabel, fieldlist))
        d1 = {'token': auth.loc[auth.study == study, 'token'].values[0], 'content': 'record', 'format': 'csv', 'type': 'flat',
              'fields[0]': auth.loc[auth.study == study, 'field'].values[0],
              'fields[1]': auth.loc[auth.study == study, 'interview_date'].values[0],
              'fields[2]': auth.loc[auth.study == study, 'sexatbirth'].values[0],
              'fields[3]': auth.loc[auth.study == study, 'sitenum'].values[0],
              'fields[4]': auth.loc[auth.study == study, 'dobvar'].values[0]}
        d2 = fieldrow
        d3 = {'events[0]': auth.loc[auth.study == study, 'event'].values[0], 'rawOrLabel': 'raw', 'rawOrLabelHeaders': 'raw',
              'exportCheckboxLabel': 'false',
              'exportSurveyFields': 'false', 'exportDataAccessGroups': 'false', 'returnFormat': 'json'}
        data = {**d1, **d2, **d3}
        buf = BytesIO()
        ch = pycurl.Curl()
        ch.setopt(ch.URL, 'https://redcap.wustl.edu/redcap/srvrs/prod_v3_1_0_001/redcap/api/')
        ch.setopt(ch.HTTPPOST, list(data.items()))
        ch.setopt(ch.WRITEDATA, buf)
        ch.perform()
        ch.close()
        htmlString = buf.getvalue().decode('UTF-8')
        buf.close()
        parent_ids = pd.DataFrame(htmlString.splitlines(), columns=['row'])
        header = parent_ids.iloc[0]
        headerv2 = header.str.replace(auth.loc[auth.study == study, 'interview_date'].values[0], 'interview_date')
        headerv3 = headerv2.str.split(',')
        parent_ids.drop([0], inplace=True)
        pexpanded = pd.DataFrame(parent_ids.row.str.split(pat=',').values.tolist(), columns=headerv3.values.tolist()[0])
        # pexpanded=pexpanded.loc[~(pexpanded.subject_id=='')]
        # new=pexpanded['subject_id'].str.split("_",1,expand=True)
        pexpanded = pexpanded.loc[~(pexpanded[auth.loc[auth.study == study, 'field'].values[0]] == '')]  ##
        new = pexpanded[auth.loc[auth.study == study, 'field'].values[0]].str.split("_", 1, expand=True)
        pexpanded['subject'] = new[0].str.strip()
        pexpanded['flagged'] = new[1].str.strip()
        pexpanded['study'] = study  # auth.study[i]
        studydata = pd.concat([studydata, pexpanded], axis=0, sort=True)
        # Convert age in years to age in months
        # note that dob is hardcoded var name here because all redcap databases use same variable name...sue me
        # interview date, which was originally v1_date for hcpa, has been renamed in line above, headerv2
        try:
            studydata['nb_months'] = (
                    12 * (pd.to_datetime(studydata['interview_date']).dt.year - pd.to_datetime(studydata.dob).dt.year) +
                    (pd.to_datetime(studydata['interview_date']).dt.month - pd.to_datetime(studydata.dob).dt.month) +
                    (pd.to_datetime(studydata['interview_date']).dt.day - pd.to_datetime(studydata.dob).dt.day) / 31)
            studydatasub=studydata.loc[studydata.nb_months.isnull()].copy()
            studydatasuper = studydata.loc[~(studydata.nb_months.isnull())].copy()
            studydatasuper['nb_months'] = studydatasuper['nb_months'].apply(np.floor).astype(int)
            studydatasuper['nb_monthsPHI'] = studydatasuper['nb_months']
            studydatasuper.loc[studydatasuper.nb_months > 1080, 'nb_monthsPHI'] = 1200
            studydata=pd.concat([studydatasub,studydatasuper],sort=True)
            studydata = studydata.drop(columns={'nb_months'}).rename(columns={'nb_monthsPHI': 'interview_age'})
        except:
            pass
        return studydata

##########################################

    def getredcapids(self): #, token=token[0],field=field[0],event=event[0]):
        """
        Downloads field (IDS) in Redcap databases specified by details in redcapconfig file
        Returns panda dataframe with fields 'study', 'Subject_ID, 'subject', and 'flagged', where 'Subject_ID' is the 
        patient id in the database of interest (sometimes called subject_id, parent_id). 
        subject is this same id stripped of underscores or flags like 'excluded' to make it easier to merge
        flagged contains the extra characters other than the id so you can keep track of who should NOT be uploaded to NDA
         or elsewwhere shared
        """
        auth = pd.read_csv(redcapconfigfile)
        studyids=pd.DataFrame()
        for i in range(len(auth.study)):
            data = {
                'token': auth.token[i],  'content': 'record','format': 'csv', 'type': 'flat',  'fields[0]': auth.field[i],
                'events[0]': auth.event[i], 'rawOrLabel': 'raw', 'rawOrLabelHeaders': 'raw',    'exportCheckboxLabel': 'false',
                'exportSurveyFields': 'false', 'exportDataAccessGroups': 'false',   'returnFormat': 'json'  }
            buf = BytesIO()
            ch = pycurl.Curl()
            ch.setopt(ch.URL, 'https://redcap.wustl.edu/redcap/srvrs/prod_v3_1_0_001/redcap/api/')
            ch.setopt(ch.HTTPPOST, list(data.items()))
            ch.setopt(ch.WRITEDATA, buf)
            ch.perform()
            ch.close()
            htmlString = buf.getvalue().decode('UTF-8')
            buf.close()
            parent_ids=pd.DataFrame(htmlString.splitlines(),columns=['Subject_ID'])
            parent_ids=parent_ids.iloc[1:,]
            parent_ids=parent_ids.loc[~(parent_ids.Subject_ID=='')]
            uniqueids=pd.DataFrame(parent_ids.Subject_ID.unique(),columns=['Subject_ID'])
            uniqueids['Subject_ID']=uniqueids.Subject_ID.str.strip('\'"')
            new=uniqueids['Subject_ID'].str.split("_",1,expand=True)
            uniqueids['subject']=new[0].str.strip()
            uniqueids['flagged']=new[1].str.strip()
            uniqueids['study']=auth.study[i]
            studyids=studyids.append(uniqueids)
        return studyids


 
if __name__ == '__main__':
    box = LifespanBox()

    

    results = box.search(
        pattern='-Aging_scores.csv',
        limit=10,
        maxresults=10
    )
    for r in results[0:49]:
        print(r)
    print('^ {} results'.format(len(results)))
