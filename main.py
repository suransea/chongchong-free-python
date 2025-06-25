import re
import os
import sys
import json
import argparse
import requests
from ccmz import LibCCMZ

def httpget(url, headers=None):
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text

def boolean_string(val, detailed=False):
    return "是" if val else "否" if not detailed else ("✔️" if val else "❌")

def get_music_id(param):
    match = re.search(r'(\d+)', param)
    return match.group(1) if match else None

def get_opern_id(music_id):
    url = f"https://www.gangqinpu.com/cchtml/{music_id}.htm"
    text = httpget(url)
    match = re.search(r'data-oid="(\d+)"', text)
    if not match:
        print("OpernID找不到")
        return None
    return match.group(1)

def get_details(opern_id):
    api = 'https://www.gangqinpu.com/api/home/user/getOpernDetail?'
    params = f"service_type=ccgq&platform=web-ccgq&service_uid=&service_key=&ccgq_uuid=&uid=&id={opern_id}"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.0.0 Safari/537.36"
    }
    return httpget(api + params, headers=headers)

def safe_filename(name):
    return ''.join(c if c not in '/\\:*?"<>|' else ' ' for c in name)

def number2alphabet(num):
    if num < 1 or num > 26:
        raise ValueError("Number must be between 1 and 26")
    return chr(num + ord('A') - 1)

import json

def convert_to_lilypond(json_data, details):
    if isinstance(json_data, str):
        data = json.loads(json_data)
    else:
        data = json_data
    
    # Extract key information
    key_signature = data.get("fifths", 5)  # Default to 5 if not specified
    
    # Setup LilyPond header
    lily_output = fr'''\version "2.20.0"

\header {{
  title = "{details['name']}"
  composer = "{details['typename']}"
  arranger = "{details['author']}"
  tagline = ##f
}}
'''
    
    # Map step numbers to note names
    step_map = {1: "c", 2: "d", 3: "e", 4: "f", 5: "g", 6: "a", 7: "b"}
    
    # Map note type to LilyPond duration and actual fraction value
    duration_map = {
        1: ("1", 4),      # Whole note = 4 quarter notes
        2: ("2", 2),      # Half note = 2 quarter notes
        4: ("4", 1),      # Quarter note = 1 quarter note
        8: ("8", 0.5),    # Eighth note = 0.5 quarter notes
        16: ("16", 0.25), # Sixteenth note = 0.25 quarter notes
        32: ("32", 0.125) # Thirty-second note = 0.125 quarter notes
    }
    
    # Handle dotted notes by adjusting duration
    def get_duration_with_dot(note_type, dot_count=0):
        lily_dur, base_value = duration_map.get(note_type, ("4", 1))
        dot_value = base_value
        total_value = base_value
        
        for _ in range(dot_count):
            dot_value /= 2
            total_value += dot_value
        
        lily_dur_with_dots = lily_dur + "." * dot_count
        return lily_dur_with_dots, total_value
    
    # Map key signature (fifths) to LilyPond key
    key_map = {
        0: "c \\major",
        1: "g \\major",
        2: "d \\major",
        3: "a \\major",
        4: "e \\major",
        5: "b \\major",
        6: "fis \\major",
        7: "cis \\major",
        -1: "f \\major",
        -2: "bes \\major",
        -3: "ees \\major",
        -4: "aes \\major",
        -5: "des \\major",
        -6: "ges \\major",
        -7: "ces \\major",
    }

    # Create a dictionary to track tied notes
    tied_notes = {}
    
    # Scan for tied notes to build the tracking dictionary
    for part_idx, part in enumerate(data.get("parts", [])):
        for measure_idx, measure in enumerate(part.get("measures", [])):
            for note_idx, note in enumerate(measure.get("notes", [])):
                if "elems" in note:
                    for elem_idx, elem in enumerate(note["elems"]):
                        # Check for pairs that indicate ties
                        if "pairs" in elem:
                            for pair in elem["pairs"]:
                                if pair.get("type") == "tied":
                                    note_id = elem.get("id")
                                    tied_notes[note_id] = True
                        # Check for tied end markers
                        if "tied" in elem and elem["tied"] == "end":
                            # This is the ending of a tie
                            # The starting note should have been marked in the pairs loop
                            pass

    def process_staff(measures, staff_num):
        staff_output = []
        current_time_sig = (4, 4)  # Default 4/4 time
        
        for measure_idx, measure in enumerate(measures):
            measure_notes = []
            measure_duration = 0  # Track actual duration of notes in the measure
            
            # Get time signature if available
            if "time" in measure:
                time_sig = measure["time"]
                beats = int(time_sig["beats"])
                beat_unit = int(time_sig["beatu"])
                current_time_sig = (beats, beat_unit)
                staff_output.append(f'  \\time {beats}/{beat_unit}')
            
            # Calculate target measure duration (in quarter notes)
            target_duration = (current_time_sig[0] * 4) / current_time_sig[1]
            
            # Filter notes for the current staff
            staff_notes = [n for n in measure.get("notes", []) if n.get("staff") == staff_num]
            
            # Sort notes by tick
            staff_notes.sort(key=lambda n: n.get("tick", 0))
            
            # Group notes by tick for chord detection
            notes_by_tick = {}
            for note in staff_notes:
                tick = note.get("tick", 0)
                if tick not in notes_by_tick:
                    notes_by_tick[tick] = []
                notes_by_tick[tick].append(note)
            
            # Process each tick group
            for tick, notes in sorted(notes_by_tick.items()):
                if len(notes) > 1:  # Multiple notes at the same tick = chord
                    chord_notes = []
                    has_tie = False
                    has_arpeggio = False
                    
                    # Check for arpeggio
                    for note in notes:
                        if "arts" in note:
                            for art in note.get("arts", []):
                                if art.get("type") == "arpeggiate":
                                    has_arpeggio = True
                    
                    # Collect all pitches from all notes at this tick
                    for note in notes:
                        if "elems" in note:
                            for elem in note["elems"]:
                                pitch = step_map.get(elem.get("step"), "c")
                                
                                # Handle accidentals
                                if elem.get("alter") == 1:
                                    pitch += "is"
                                elif elem.get("alter") == 2:
                                    pitch += "isis"  # Double sharp
                                elif elem.get("alter") == -1:
                                    pitch += "es"
                                elif elem.get("alter") == -2:
                                    pitch += "eses"  # Double flat
                                
                                octave = elem.get("octave", 4)
                                lily_octave = "'" * (octave - 3) if octave > 3 else "," * (3 - octave)
                                chord_notes.append(f"{pitch}{lily_octave}")
                                
                                # Check for ties
                                if elem.get("id") in tied_notes:
                                    has_tie = True
                    
                    # Use the duration of the first note for the entire chord
                    note_type = notes[0].get("type", 4)
                    dot_count = notes[0].get("dots", 0)
                    if "dots" not in notes[0] and notes[0].get("dot") == 1:
                        dot_count = 1
                    lily_dur, note_value = get_duration_with_dot(note_type, dot_count)
                    measure_duration += note_value
                    
                    if chord_notes:
                        chord_text = f"<{' '.join(chord_notes)}>{lily_dur}"
                        if has_arpeggio:
                            chord_text += " \\arpeggio"
                        if has_tie:
                            chord_text += " ~"
                        measure_notes.append(chord_text)
                
                else:  # Single note/rest at this tick
                    note = notes[0]
                    note_type = note.get("type", 4)
                    dot_count = note.get("dots", 0)
                    if "dots" not in note and note.get("dot") == 1:
                        dot_count = 1
                    lily_dur, note_value = get_duration_with_dot(note_type, dot_count)
                    measure_duration += note_value
                    
                    if "rest" in note:
                        measure_notes.append(f"r{lily_dur}")
                    elif "elems" in note:
                        # Check if this is a chord represented as multiple elements in a single note
                        if len(note["elems"]) > 1:
                            chord_notes = []
                            has_tie = False
                            has_arpeggio = False
                            
                            # Check for arpeggio
                            if "arts" in note:
                                for art in note.get("arts", []):
                                    if art.get("type") == "arpeggiate":
                                        has_arpeggio = True
                            
                            for elem in note["elems"]:
                                pitch = step_map.get(elem.get("step"), "c")
                                
                                # Handle accidentals
                                if elem.get("alter") == 1:
                                    pitch += "is"
                                elif elem.get("alter") == 2:
                                    pitch += "isis"  # Double sharp
                                elif elem.get("alter") == -1:
                                    pitch += "es"
                                elif elem.get("alter") == -2:
                                    pitch += "eses"  # Double flat
                                    
                                octave = elem.get("octave", 4)
                                lily_octave = "'" * (octave - 3) if octave > 3 else "," * (3 - octave)
                                chord_notes.append(f"{pitch}{lily_octave}")
                                
                                # Check for ties
                                if elem.get("id") in tied_notes:
                                    has_tie = True
                            
                            chord_text = f"<{' '.join(chord_notes)}>{lily_dur}"
                            if has_arpeggio:
                                chord_text += " \\arpeggio"
                            if has_tie:
                                chord_text += " ~"
                            measure_notes.append(chord_text)
                        else:
                            # Single note
                            elem = note["elems"][0]
                            pitch = step_map.get(elem.get("step"), "c")
                            
                            # Handle accidentals
                            if elem.get("alter") == 1:
                                pitch += "is"
                            elif elem.get("alter") == 2:
                                pitch += "isis"  # Double sharp
                            elif elem.get("alter") == -1:
                                pitch += "es"
                            elif elem.get("alter") == -2:
                                pitch += "eses"  # Double flat
                                
                            octave = elem.get("octave", 4)
                            lily_octave = "'" * (octave - 3) if octave > 3 else "," * (3 - octave)
                            note_text = f"{pitch}{lily_octave}{lily_dur}"
                            
                            # Check for tie
                            if elem.get("id") in tied_notes:
                                note_text += " ~"
                            
                            measure_notes.append(note_text)
            
            # Check if measure has the correct duration, add rests if needed
            if abs(measure_duration - target_duration) > 0.001:
                # Calculate how much rest duration is needed
                missing_duration = target_duration - measure_duration
                
                # Only add rests if we're missing time
                if missing_duration > 0:
                    # Add appropriate rests to make up the difference
                    rest_durations = []
                    remaining = missing_duration
                    
                    # Try to add rests in decreasing size
                    for dur_type, (lily_dur, dur_value) in sorted(
                        [(k, (v, val)) for k, (v, val) in duration_map.items()], 
                        key=lambda x: x[1][1], 
                        reverse=True
                    ):
                        while remaining >= dur_value:
                            rest_durations.append(lily_dur)
                            remaining -= dur_value
                    
                    # Add the rests to the measure
                    for rest_dur in rest_durations:
                        measure_notes.append(f"r{rest_dur}")
            
            staff_output.append(f"  {' '.join(measure_notes)} |")
        
        return staff_output
    
    # Process parts
    for part_idx, part in enumerate(data.get("parts", [])):
        measures = part.get("measures", [])
        
        # Define right hand (upper staff)
        lily_output += f'\nright{number2alphabet(part_idx + 1)} = ' + "{\n"
        lily_output += f'  \\clef treble\n'
        lily_output += f'  \\key {key_map.get(key_signature, "b \\major")}\n'
        
        # Process right hand measures
        right_hand = process_staff(measures, 1)
        lily_output += '\n'.join(right_hand) + "\n}\n"
        
        # Define left hand (lower staff)
        lily_output += f'\nleft{number2alphabet(part_idx + 1)} = ' + "{\n"
        lily_output += f'  \\clef bass\n'
        lily_output += f'  \\key {key_map.get(key_signature, "b \\major")}\n'
        
        # Process left hand measures
        left_hand = process_staff(measures, 2)
        lily_output += '\n'.join(left_hand) + "\n}\n"
    
    # Create the piano staff
    lily_output += '''
\\score {
  \\new PianoStaff <<
    \\new Staff = "upper" \\rightA
    \\new Staff = "lower" \\leftA
  >>
  \\layout { }
  \\midi { \\tempo 4 = 80 }
}
'''
    
    return lily_output

def main():
    parser = argparse.ArgumentParser(description="虫虫钢琴钢琴谱midi下载")
    parser.add_argument('-i', '--id', required=True, help='琴谱id或url')
    parser.add_argument('-o', '--output', default='./output', help='保存目录（默认output）')
    args = parser.parse_args()

    input_param = args.id
    save_dir = args.output
    music_id = get_music_id(input_param)
    if not music_id:
        print("无法识别id")
        sys.exit(1)

    os.makedirs(save_dir, exist_ok=True)

    opern_id = get_opern_id(music_id)
    if not opern_id:
        print("无法获取OpernID，退出。")
        sys.exit(1)
    all_details = json.loads(get_details(opern_id))
    details = all_details['list']
    ccmz_link = details['play_json']
    music_name = details['name']
    paid = details['is_pay']
    typename = details['typename']
    authorc_name = details['author']

    file_name = f"{safe_filename(music_name)}-{typename}"

    print(f"付费歌曲: {boolean_string(paid == '1')}")
    print(f"音乐名: {music_name}")
    print(f"原作者: {typename}")
    print(f"上传人: {authorc_name}")

    if ccmz_link:
        ccmz_raw = LibCCMZ.download_ccmz(ccmz_link)
        def cb(info):
            midi_path = os.path.join(save_dir, f"{file_name}.mid")
            if info.ver == 2:
                midi_data = json.loads(info.midi)
                LibCCMZ.write_midi(midi_data, midi_path)
                with open(os.path.join(save_dir, f"{file_name}.json"), "wb") as f:
                    f.write(info.score.encode('utf-8'))
                with open(os.path.join(save_dir, f"{file_name}.ly"), "wb") as f:
                    f.write(convert_to_lilypond(info.score, details).encode('utf-8'))
            else:
                with open(midi_path, "wb") as f:
                    f.write(info.midi.encode("latin1"))
            print(f"下载成功! 已保存MIDI文件：{midi_path}")
        LibCCMZ.read_ccmz(ccmz_raw, cb)
    else:
        print('无MIDI可下载')

if __name__ == "__main__":
    main()
