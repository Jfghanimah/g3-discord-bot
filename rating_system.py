import math
import statistics


def new_team_ratings(team1, team2, score):
    #team1 = [(1500,350),(1500,350),(1500,350),(1500,350),(1500,350)]
    #team2 = [(1500,350),(1500,350),(1500,350),(1500,350),(1500,350)]
    # score = 1 means team 1 win, score = 0 means team 2 win

    new_team1 = []
    new_team2 = []
    delta_team1 = []
    delta_team2 = []
    
    # Calculate the average rating and stdev for the teams
    avg_rating_t1 = statistics.mean([player[0] for player in team1]) # Probably should do a weighted average 
    avg_stdev_t1 = statistics.mean([player[1] for player in team1])
    avg_rating_t2 = statistics.mean([player[0] for player in team2]) # Probably should do a weighted average 
    avg_stdev_t2 = statistics.mean([player[1] for player in team2])

    # Calculate new ratings and stdevs for each player on team 1 
    # by playing them against the average 'player' that represents team 2
    # also pretend that player had the elo of their average team
    for player in team1:
        rating_delta, stdev_delta = rating_change(avg_rating_t1, player[1], avg_rating_t2, avg_stdev_t2, score)
        delta_team1.append(rating_delta)
        new_team1.append((player[0] + rating_delta, player[1] + stdev_delta))
        
    # Calculate new ratings and stdevs for each player on team 2 
    # by playing them against the average 'player' that represents team 1
    # also pretend that player had the elo of their average team 
    for player in team2:
        rating_delta, stdev_delta = rating_change(avg_rating_t2, player[1], avg_rating_t1, avg_stdev_t1, 1-score)
        delta_team2.append(rating_delta)
        new_team2.append((player[0] + rating_delta, player[1] + stdev_delta))
        
    return new_team1, new_team2, delta_team1, delta_team2


# Use this to calculate change of a player to another player
# Score of 1 means we've won, 0 is loss
def rating_change(rating1, stdev1, rating2, stdev2, score):
    r1_og = rating1
    s1_og = stdev1

    # Step 1: Set the factor for scaling the ratings and stdevs
    factor = 173.7178 #400/ln(10)

    # Step 2: Calculate the internal ratings and stdevs
    # Convert ratings and stdevs to the internal scale for every calculation
    rating1 = (rating1 - 1500) / factor
    rating2 = (rating2 - 1500) / factor
    stdev1 = stdev1 / factor
    stdev2 = stdev2 / factor

    # Step 3: Calculate v, a measure of the amount of uncertainty in the match
    v_uncertainty = (g(stdev2)**2 * E(rating1, rating2, stdev2) * (1 - E(rating1, rating2, stdev2)))**(-1)

    # Step 4: Calculate the internal rating stdev after the match
    stdev1_star = math.sqrt(stdev1**2 + 0.06**2)
    stdev1_prime = 1 / math.sqrt(1 / stdev1_star**2 + 1 / v_uncertainty)

    rating1_prime = rating1 + stdev1_prime**2 * g(stdev2) * (score - E(rating1, rating2, stdev2))

    # Step 8: Lastly we convert rating and stdev back to original scale
    rating1_delta = round(rating1_prime * factor + 1500) - r1_og
    stdev1_delta = round(stdev1_prime * factor) - s1_og

    return rating1_delta, stdev1_delta

        
# g helps calculate how impervious a rating is to change. Sort of like its intertial mass.
def g(stdev):
    return 1 / math.sqrt(1 + 3 * stdev**2 / math.pi**2)


# E calculates expected outcome of a match given two ratings and the stdev of the opponent
def E(rating1, rating2, stdev2):
    return 1 / (1 + math.exp(-g(stdev2) * (rating1 - rating2)))