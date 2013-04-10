#! /usr/bin/env python2.7
# -*- coding: utf-8 -*-
import requests
from flask import redirect, url_for, \
    render_template, jsonify, request, \
    send_from_directory
import datetime
import logging
import sys
from math import log10
import codecs

from models import DB_Stop, DB_Train, VBB_Stop, Bvg_line, app, db
from helpers import print_success, print_failure


logging.basicConfig(filename="rechecks.log",
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    level=logging.INFO)
if "--verbose" in sys.argv:
    console = logging.StreamHandler(sys.stdout)
    logging.getLogger('').addHandler(console)


@app.route("/")
def main():
    ''' The main page '''
    return pagination(1)


@app.route("/city/<city>/page/<number>")
def pagination(number, city="Ulm"):
    """ Render only 100 stops for better overview"""
    number = int(number)
    start = (number-1)*50
    stop = number * 50
    q = DB_Stop.query\
        .filter(DB_Stop.landkreis == city)\
        .order_by("last_run desc").all()
    Stops = q[start:stop]
    all_stops = len(q)
    matches = len([stop for stop in q if stop.matches > 0])
    landkreise = list(set([stop.landkreis for stop in
                           DB_Stop.query.all()]))
    landkreise.sort()

    for stop in Stops:
        stop.turbo_url = VBB_Stop(stop.to_vbb_syntax()).turbo_url

    return render_template("index.html",
                           city=city,
                           stops=Stops,
                           pages=all_stops,
                           this_page=number,
                           matches_count=matches,
                           landkreise=landkreise
                           )


@app.route("/search/<query>")
def search(query):
    """ Return a list with all the stops that match the query"""
    Stops = DB_Stop.query.filter(DB_Stop.name.like("%" + query + "%")).all()

    for stop in Stops:
        stop.turbo_url = VBB_Stop(stop.to_vbb_syntax()).turbo_url

    return render_template("index.html", stops=Stops, pages=False)


@app.route("/stops/<show_only>/<north>/<east>/<south>/<west>")
def stops_in_bounding_box(show_only, north, east, south, west):
    ''' Only show stops within a given bounding box. Allow filtering by
    matches/nomatches'''
    if show_only == "problemsonly":
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
            DB_Stop.matches == 0
        ).all()

    elif show_only == "matchesonly":
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
            DB_Stop.matches > 0
        ).all()
    else:
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
        ).all()

    landkreise = list(set([stop.landkreis for stop in
                           DB_Stop.query.all()]))
    landkreise.sort()
    return render_template("index.html",
                           stops=result,
                           landkreise=landkreise
                           )


@app.route("/api/jsonstops/<show_only>/<north>/<east>/<south>/<west>")
def json_stops(show_only, north, east, south, west):
    ''' Only show stops within a given bounding box. Allow filtering by
    matches/nomatches'''
    if show_only == "problemsonly":
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
            DB_Stop.matches == 0
        ).all()

    elif show_only == "matchesonly":
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
            DB_Stop.matches > 0
        ).all()
    else:
        result = DB_Stop.query.filter(
            DB_Stop.lat.between(float(south), float(north)),
            DB_Stop.lon.between(float(west), float(east)),
        ).all()

    all_stops = []
    for stop in result:
        all_stops.append(stop.to_dict())
        if len(all_stops) > 100:
            return jsonify(stops="Too many")

    return jsonify(stops=all_stops)


@app.route("/recheck/<id>")
def recheck(id, from_cm_line=False):
    ''' Rerun the checks for a stop and update the db'''
    stop = DB_Stop.query.filter_by(id=id).first()
    old_matches = stop.matches
    stop.matches = VBB_Stop(stop.to_vbb_syntax(), stop.exception).is_in_osm()
    stop.last_run = datetime.datetime.now().replace(microsecond=0)
    db.session.commit()
    if not from_cm_line:
        logging.info("[recheck] Name: %-5s; Old: %-3i; New: %-3i; IP: %-3s" % (stop.name,
                                                                       old_matches,
                                                                       stop.matches,
                                                                       request.remote_addr))
        return redirect(url_for("pagination", number=1, city=stop.landkreis))
    else:
        if stop.matches > 0:
            print_success("%s now matches %i stops" % (stop.name,
                                                       stop.matches))
        else:
            print_failure("%s does not match any stops..." % (stop.name))
        return stop.matches


@app.route("/map_of_the_bad")
def map_of_the_bad():
    ''' Return a map with all the stops that aren't in OSM '''
    return render_template("map.html")


@app.route("/api/stops")
def api_stops():
    if request.args.get("matchesOnly"):
        Stops = DB_Stop.query.filter(DB_Stop.matches >= 1).all()
    elif request.args.get("noMatchesOnly"):
        Stops = DB_Stop.query.filter(DB_Stop.matches < 1).all()
    else:
        Stops = DB_Stop.query.all()

    all_stops = []
    for stop in Stops:
        all_stops.append(stop.to_dict())
    return jsonify(stops=all_stops)


@app.route('/exceptions', methods=["get", "post"])
def match_exceptions():
    if request.method == "POST":
        if request.form["id"] and request.form["string"]:
            stop = DB_Stop.query.filter_by(id=int(request.form["id"])).first()
            stop.exception = request.form["string"]
            db.session.commit()
            return redirect(url_for("match_exceptions"))
    all_stops = DB_Stop.query.all()
    exceptions = [Stop for Stop in all_stops if Stop.exception]
    return render_template("exceptions.html", all_stops=all_stops, exceptions=exceptions)


@app.route('/robots.txt')
def serve_static():
    return send_from_directory(app.static_folder, request.path[1:])


def get_trains():
    ''' The initial query to set up the train db '''
    url = "http://datenfragen.de/openvbb/GTFS_VBB_Okt2012/routes.txt"
    req = requests.get(url)
    text = req.text.split("\n")
    for line in text:
        Train = Bvg_line(line)
        if Train.operator in ["BVG", "DB"]:
            feedback = Train.is_in_osm()
            if feedback:
                print_success(feedback)
            else:
                print_failure(Train.line_number + " is not in OSM")
            db_rep = DB_Train()
            db.session.add(db_rep)
            db.session.commit()


def recheck_batch(Stops):
    ids = [Stop.id for Stop in Stops]
    total = 0
    number_of_stops = len(Stops)
    # get the number of digits we want to show
    digits = int(log10(number_of_stops)) + 1
    counter = 0
    for Stop in Stops:
        counter += 1
        print "%*i/%*i " % (digits, counter, digits, number_of_stops),
        out = recheck(Stop.id, from_cm_line=True)
        if out > 0:
            total += 1
    print_success("Insgesamt %i neue Treffer" % total)


def recheck_all_missings_stops():
    Stops = DB_Stop.query.filter(DB_Stop.matches < 1).all()
    recheck_batch(Stops)


def recheck_by_name(name):
    Stops = DB_Stop.query.filter(DB_Stop.name.like("%" + name + "%"),
                                 DB_Stop.matches < 1).all()
    recheck_batch(Stops)


def recheck_all():
    Stops = DB_Stop.query.all()
    recheck_batch(Stops)


def get_stops():
    ''' The initial query to set up the stop db '''
    all_stops = DB_Stop.query.all()
    all_ids = [stop.id for stop in all_stops]
    url = "http://www.swu.de/fileadmin/gtfs/stops.txt"
    req = requests.get(url)
    req.encoding = "utf-8"
    text = req.text.split("\n")[1:]
    for line in text:  # start in line 35 to exlclude stops in Poland
        if len(line) > 1:
            Stop = VBB_Stop(line)
            if Stop.stop_id not in all_ids and int(Stop.ismainstation) != 0:
                feedback = Stop.is_in_osm()
                if feedback > 0:
                    print_success(Stop.name + ": " + str(feedback))
                else:
                    print_failure(Stop.name + ":  0")
                new_stop = DB_Stop(
                    name=Stop.name,
                    lat=Stop.lat,
                    lon=Stop.lon,
                    matches=feedback,
                    vbb_id=Stop.stop_id
                )
                db.session.add(new_stop)
                db.session.commit()


if __name__ == "__main__":
    app.debug = True
    app.run()
