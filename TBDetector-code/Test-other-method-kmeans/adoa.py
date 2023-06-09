

import numpy as np  
from sklearn.ensemble import IsolationForest
from cluster_centers import get_cluster_centers
from sklearn.preprocessing import StandardScaler, minmax_scale

class ADOA:
    """Implementation of ADOA (Anomaly Detection with Partially Observed Anomalies)"""
    def __init__(self, anomalies, unlabel, classifer, cluster_algo='kmeans', n_clusters='auto', 
                 contamination=0.01, theta=0.85, alpha='auto', beta='auto', return_proba=False, 
                 random_state=2018,percent=45,gailv=1.0):
        '''
        :param anomalies: Observed anomaly data sets
        
        :param unlabel:  Unlabeled data sets.
        
        :param classifer: A Classifer fitting weighted samples and labels to predict unlabel samples.
        
        :param cluster_algo: str, {'kmeans'、'spectral'、'birch'、'dbscan'}, default = 'kmeans'
             Clustering algorithm for clustering anomaly samples.      
              
        :param n_clusters: int, default=5
             The number of clusters to form as well as the number of centroids to generate.
        
        :param contamination : float, range (0, 0.5).
              The proportion of outliers in the data set. 数据集中异常值的比例。

        :param theta : float, range [0, 1].
              The weights of isolation_score and similarity_score are theta and 1-theta respectively.
              
        :param alpha : float, should be positive number, default = mean value of anomalies's score
              Threshold value for determining unlabel sample as potential anomaly
              
        :param beta : float, should be positive number
              Threshold value for determining unlabel sample as reliable normal sample

        :param return_proba : bool, default=False
              Whether return the predicted probability for positive(anomaly) class for each sample.
              Need classifer to provide predict_proba method.
        '''
        dataset_scaled = StandardScaler().fit_transform(np.r_[anomalies, unlabel])
        self.anomalies = dataset_scaled[:len(anomalies), :] 
        self.unlabel = dataset_scaled[len(anomalies):, :] 
        self.contamination = contamination
        self.classifer = classifer 
        self.n_clusters = n_clusters
        self.cluster_algo = cluster_algo
        self.theta = theta 
        self.alpha = alpha 
        self.beta = beta 
        self.return_proba = return_proba 
        self.random_state = random_state
        self.percent = percent
        self.gailv=gailv
        self.centers, self.cluster_score = get_cluster_centers(self.anomalies, self.n_clusters, self.cluster_algo)
    
    def cal_weighted_score(self):
        dataset = np.r_[self.anomalies, self.unlabel]
        # print("dataset:",dataset)
        # print("IsolationForest---contamination:",self.contamination)
        iforest = IsolationForest(n_estimators=100, contamination=self.contamination, 
                                  random_state=self.random_state, n_jobs=-1)
        iforest.fit(dataset)  
        # Paper：The higher is the score IS(x) (close to 1), the more likely that x being an anomaly.
        # Scikit-learn API : decision_function(X): The lower, the more abnormal.
        isolation_score = -iforest.decision_function(dataset)
        isolation_score_scaled = minmax_scale(isolation_score)
        
        def cal_similarity_score(arr, centers=self.centers):
            min_dist = np.min([np.square(arr - center).sum() for center in centers])
            similarity_score = np.exp(-min_dist/len(arr))
            '''
            In the paper, when calculating similarity_score, min_dist is not divided by the number of features 
            (len(arr)), but when the number of features is large, the value of np.exp(min_dist) is very large, 
            so that similarity_score is close to 0, which lacks weighted meaning. Dividing by the number of 
            features helps to alleviate this phenomenon and does not affect the ordering of similarity_score.  
            '''
            return similarity_score
        similarity_score = [cal_similarity_score(arr) for arr in dataset]
        similarity_score_scaled = minmax_scale(similarity_score)
        # print("isolation_score_scaled:",isolation_score_scaled)
        # print("similarity_score_scaled:",similarity_score_scaled)
        # print("self.theta * isolation_score_scaled:",self.theta * isolation_score_scaled)
        # print("(1-self.theta) * similarity_score_scaled:",(1-self.theta) * similarity_score_scaled)
        weighted_score = self.theta * isolation_score_scaled + (1-self.theta) * similarity_score_scaled
        # print("weighted_score:",weighted_score)
        return weighted_score
    
    def determine_trainset(self):
        weighted_score = self.cal_weighted_score()
        min_score, max_score, median_score = [func(weighted_score) for func in (np.min, np.max, np.median)]
        anomalies_score = weighted_score[:len(self.anomalies)]
        unlabel_scores = weighted_score[len(self.anomalies):]
        print("unlabel_scores:",unlabel_scores)
        percent = self.percent
        # determine the value of alpha、beta
        self.alpha = ((np.mean(anomalies_score)+min_score)/2)*self.gailv if self.alpha == 'auto' else self.alpha
        self.beta = median_score if median_score < self.alpha else np.percentile(weighted_score, percent)
        while self.beta >= self.alpha:
            percent -= 5
            # print("percent:", percent)
            if percent == 0:
                self.beta = self.alpha * 0.9
                break
            self.beta = np.percentile(weighted_score, percent)
        assert self.beta < self.alpha, 'beta should be smaller than alpha.'
        
        # rlb:reliabel, ptt:potential
        rlb_bool, ptt_bool = unlabel_scores <= self.beta, unlabel_scores>=self.alpha
        # print("rlb_bool:",rlb_bool)
        # print("rlb_bool的大小:", len(rlb_bool))
        print("self.beat:", self.beta)
        print("self.alpha:", self.alpha)
        # print("ptt_bool:",ptt_bool)
        ptt_normal, rlb_anomalies = self.unlabel[ptt_bool], self.unlabel[rlb_bool]
        rlb_anomalies_score, ptt_normal_score = unlabel_scores[rlb_bool], unlabel_scores[ptt_bool]
        rlb_anomalies_weight = (max_score-rlb_anomalies_score)/(max_score-min_score)
        ptt_normal_weight = ptt_normal_score/max_score

        
        normal_weight = normal_label = np.ones(len(self.anomalies))
        X_train = np.r_[self.anomalies, ptt_normal, rlb_anomalies]
        weights = np.r_[normal_weight, ptt_normal_weight, rlb_anomalies_weight]
        y_train = np.r_[normal_label, np.ones(len(ptt_normal)), np.zeros(len(rlb_anomalies))].astype(int)
        return X_train, y_train, weights
    
    def predict(self):
        X_train, y_train, weights = self.determine_trainset()
        clf = self.classifer
        clf.fit(X_train, y_train, sample_weight=weights)
        y_pred = clf.predict(self.unlabel)
        if self.return_proba:
            y_prob = clf.predict_proba(self.unlabel)[:, 1]
            return y_pred, y_prob
        else:
            return y_pred
        
    def __repr__(self):
        info_1 = \
        '1) The Observed Anomalies is divided into {:} clusters, and the calinski_harabasz_score is {:.2f}.\n'.\
        format(len(self.centers), self.cluster_score)
        
        y_train = self.determine_trainset()[1]
        rll_num = np.sum(y_train==0)
        ptt_num = sum(y_train)-len(self.anomalies)
      
        info_2 = "2) Reliable Normals's number = {:}, accounts for {:.2%} within the Unlabel dataset.\n".\
        format(rll_num, rll_num/len(self.unlabel))
        
        info_3 = "3) Potential Anomalies's number = {:}, accounts for {:.2%} within the Unlabel dataset.".\
        format(ptt_num, ptt_num/len(self.unlabel))
        return info_1 + info_2 + info_3
