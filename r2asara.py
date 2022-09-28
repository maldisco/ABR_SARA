# -*- coding: utf-8 -*-
from player.parser import *
from player.player import *
from base.configuration_parser import *
from r2a.ir2a import IR2A
import timeit
import http.client

class R2ASara(IR2A):

    def __init__(self, id):
        IR2A.__init__(self, id)
        self.parsed_mpd : mpd_node = ''
        self.qi : list = []
        self.initial_buffer : int = int(ConfigurationParser.get_instance().get_parameter('buffering_until'))
        self.segment_size : dict = dict()
        self.start_time : float = 0
        self.weighted_mean_rate : float = 0
        self.sample_count : int = 5
        self.segment_info : list = list()
        self.current_segment_size : int = 0
        self.current_bitrate : int = 46980
        self.alpha : int = 10
        self.beta : int = 15

    def handle_xml_request(self, msg):
        self.send_down(msg)

    def handle_xml_response(self, msg):
        self.parsed_mpd = parse_mpd(msg.get_payload())
        self.qi = self.parsed_mpd.get_qi()
        
        for number in range(1, 597):
            self.segment_size[number] = dict()

        # Getting segment sizes, which is a core part of the algorithm
        # In real world, this would be already cached and concatenated to MPD file
        # but in this case, i cant modify other parts of the project, so it'll be generated here
        # ps: exclusive to BigBuckBunny (1s segments)
        for quality in self.qi:
            port = '80'
            host_name = "45.171.101.167"
            path_name = f"http://45.171.101.167/DASHDataset/BigBuckBunny/1sec/bunny_{quality}bps/"
            connection = http.client.HTTPConnection(host_name, port)
            connection.request('GET', path_name)
            ss_file = connection.getresponse().read()
            file = ss_file.decode()
            for line in file.splitlines():
                if line.count("m4s"):
                    data = line.split('td')
                    number = int(data[3].split('.')[0].split('s')[-1])
                    size = data[7].split('<')[0].split('>')[-1]
                    size = float(size.replace('K',''))*1000 if size.count('K') else float(size.replace('M',''))*1000000 if size.count('M') else float(size)
                    self.segment_size[number][quality] = size*8

            connection.close()

        self.send_up(msg)

    def handle_segment_size_request(self, msg : SSMessage):             
        next_bitrate = None
        next_segment = min(msg.get_segment_id(), 596)
        segment_sizes = self.segment_size[next_segment]
        available_video_segments = self.whiteboard.get_amount_video_to_play() - self.initial_buffer
        available_video_duration = available_video_segments * 1 # segment duration

        if self.weighted_mean_rate == 0 or available_video_segments <= 0:
            next_bitrate = self.qi[0]
        elif float(segment_sizes[self.current_bitrate])/self.weighted_mean_rate > available_video_duration:
            for bitrate in reversed(self.qi):
                if(bitrate < self.current_bitrate):
                    if float(segment_sizes[bitrate])/self.weighted_mean_rate < available_video_duration:
                        next_bitrate = bitrate
                        break
            
            if not next_bitrate:
                next_bitrate = self.qi[0]
        elif available_video_segments <= self.alpha:
            if self.current_bitrate >= max(self.qi):
                next_bitrate = self.current_bitrate
            else:
                higher_bitrate = self.qi[self.qi.index(self.current_bitrate)+1]
                if float(segment_sizes[higher_bitrate])/self.weighted_mean_rate < available_video_duration:
                    next_bitrate = higher_bitrate
                else:
                    next_bitrate = self.current_bitrate
        elif available_video_segments <= self.beta:
            if self.current_bitrate >= max(self.qi):
                next_bitrate = self.current_bitrate
            else:
                for bitrate in reversed(self.qi):
                    if bitrate >= self.current_bitrate:
                        if float(segment_sizes[bitrate])/self.weighted_mean_rate < available_video_duration:
                            next_bitrate = bitrate
                            break

                if not next_bitrate:
                    next_bitrate = self.current_bitrate
        elif available_video_segments > self.beta:
            if self.current_bitrate >= max(self.qi):
                next_bitrate = self.current_bitrate
            else:
                for bitrate in reversed(self.qi):
                    if bitrate >= self.current_bitrate:
                        if float(segment_sizes[bitrate])/self.weighted_mean_rate > available_video_duration:
                            next_bitrate = bitrate
                            break

                if not next_bitrate:
                    next_bitrate = self.current_bitrate
        else:
            next_bitrate = self.current_bitrate

        msg.add_quality_id(next_bitrate)
        self.start_time = timeit.default_timer()
        self.send_down(msg)

    def handle_segment_size_response(self, msg):
        segment_download_time = timeit.default_timer() - self.start_time
        self.current_bitrate = msg.get_quality_id()
        current_segment = msg.get_segment_id() if msg.get_segment_id() < 597 else 1
        self.update_weighted_mean(self.segment_size[current_segment][self.current_bitrate], segment_download_time)
        self.send_up(msg)

    def update_weighted_mean(self, segment_size, segment_download_time):
        """ Method to update the weighted harmonic mean

        Args:
            segment_size (int): size of the next segment in bytes
            segment_download_time (float): download time of next segment in seconds

        Returns:
            float: weighted harmonic mean
        """
        segment_download_rate = segment_size / segment_download_time

        while(len(self.segment_info) > self.sample_count):
            self.segment_info.pop(0)
        self.segment_info.append((segment_size, segment_download_rate))
        self.weighted_mean_rate = sum([size for size, _ in self.segment_info]) / sum([s/r for s, r in self.segment_info])
        return self.weighted_mean_rate

    def initialize(self):
        pass

    def finalization(self):
        pass
