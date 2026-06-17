'''
MIT License

Copyright (c) 2024 VincentNL

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

import os
import math
import io
import struct
import numpy as np
import zlib

class decode:

    def __init__(self, files_lst=None, fmt=None, out_dir=None, args_str=None):
        self.files_lst = files_lst
        self.out_dir = out_dir
        self.fmt = fmt
        self.flip = ""  # Default value for flip
        self.log = False  # Default value for log flag
        self.silent = False  # Default value for silent flag
        self.debug = False  # Default value for debug flag

        if len(files_lst)==0 or files_lst == '':
            print('No file specified!')
            return

        if fmt is None:
            self.fmt = "png"

        if out_dir is None:
            self.out_dir = os.path.abspath(os.path.dirname(files_lst[0]))
        else:
            self.out_dir = out_dir

        # Determine out_dir
        if args_str:
            args = args_str.split()  # Split the string into individual arguments

            # Iterate through the arguments to find flip, log, and debug options
            for arg in args:
                if arg.startswith('-flip'):
                    # If -flip is found, extract the flip value
                    self.flip = arg[len('-flip'):]
                elif arg == '-log':
                    self.log = True
                elif arg == '-dbg':
                    self.debug = True
                elif arg == '-silent':
                    self.silent = True


        self.px_modes = {
            0: 'ARGB1555',
            1: 'RGB565',
            2: 'ARGB4444',
            3: 'YUV422',
            4: 'BUMP',
            5: 'RGB555',
            6: 'YUV420',
            7: 'ARGB8888',
            8: 'PAL-4',
            9: 'PAL-8',
            10: 'AUTO',
        }

        self.tex_modes = {
            1: 'Twiddled',
            2: 'Twiddled + Mips',
            3: 'Twiddled VQ',
            4: 'Twiddled VQ + Mips',
            5: 'Twiddled Pal4 (16-col)',
            6: 'Twiddled Pal4 + Mips (16-col)',
            7: 'Twiddled Pal8 (256-col)',
            8: 'Twiddled Pal8 + Mips (256-col)',
            9: 'Rectangle',
            10: 'Rectangle + Mips',
            11: 'Stride',
            12: 'Stride + Mips',
            13: 'Twiddled Rectangle',
            14: 'BMP',
            15: 'BMP + Mips',
            16: 'Twiddled SmallVQ',
            17: 'Twiddled SmallVQ + Mips',
            18: 'Twiddled Alias + Mips',
        }

        # remove companion .PVP/.PVR, filter the list
        new_list = []
        for item in files_lst:
            key = item[:-4]
            if not any(key == x[:-4] for x in new_list):
                new_list.append(item)
        files_lst = new_list

        selected_files = len(files_lst)
        current_file = 0

        # create Extracted\ACT folders
        if self.debug: print(os.path.join(out_dir, 'ACT'))

        # create log file
        if self.log:
            with open(f'{out_dir}/pvr_log.txt', 'w') as l:
                l.write('')

        while current_file < selected_files:
            if not files_lst:  # If no files are selected
                break

            cur_file = files_lst[current_file]
            file_name = os.path.split(cur_file)[1]
            filetype = cur_file[-4:].lower()
            PVR_file = cur_file[:-4] + '.pvr'
            PVP_file = cur_file[:-4] + '.pvp'
            PAL_file = cur_file[:-4] + '.pal'

            # Check if companion palette / texture files exist.
            # .pvp (PVPL) takes priority over .pal (PALT) when both are present.
            pvp_exists = os.path.exists(PVP_file)
            pal_exists = os.path.exists(PAL_file)
            pvr_exists = os.path.exists(PVR_file)

            apply_palette = True if (filetype == ".pvp" and pvr_exists) or (
                    filetype == ".pvr" and (pvp_exists or pal_exists)) else False
            act_buffer = bytearray()
            if pvp_exists:
                self.load_pvp(PVP_file, act_buffer, file_name)
            elif pal_exists:
                self.load_pal(PAL_file, act_buffer, file_name)

            if pvr_exists:
                self.load_pvr(PVR_file, apply_palette, act_buffer, file_name)

            current_file += 1

    def read_col(self,px_format, color):

        if px_format == 0:  # ARGB1555
            a = ((color >> 15) & 0x1) * 0xff
            r = int(((color >> 10) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x1f) * 0xff / 0x1f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format == 1:  # RGB565
            a = 0xff
            r = int(((color >> 11) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x3f) * 0xff / 0x3f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format == 2:  # ARGB4444
            a = ((color >> 12) & 0xf)*0x11
            r = ((color >> 8) & 0xf)*0x11
            g = ((color >> 4) & 0xf)*0x11
            b = (color & 0xf)*0x11
            return (r, g, b, a)

        elif px_format == 5:  # RGB555
            a = 0xFF
            r = int(((color >> 10) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5) & 0x1f) * 0xff / 0x1f)
            b = int((color & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format in [7]:  # ARGB8888
            a = (color >> 24) & 0xFF
            r = (color >> 16) & 0xFF
            g = (color >> 8) & 0xFF
            b = color & 0xFF
            return (r, g, b, a)

        elif px_format in [14]:  # RGBA8888
            r = (color >> 24) & 0xFF
            g = (color >> 16) & 0xFF
            b = (color >> 8) & 0xFF
            a = color & 0xFF
            return (r, g, b, a)

        elif px_format == 4:  # BUMP (VQ path) — treat as plain RGB565
            # VQ+BUMP: decode the SR 16-bit value exactly like a twiddled RGB
            # image so the codebook pixels are valid tuples.  The high byte is
            # S and the low byte is R; render as a plain greyscale-ish RGB so
            # Blender can display it and the encoder round-trips correctly.
            a = 0xFF
            r = int(((color >> 11) & 0x1f) * 0xff / 0x1f)
            g = int(((color >> 5)  & 0x3f) * 0xff / 0x3f)
            b = int(( color        & 0x1f) * 0xff / 0x1f)
            return (r, g, b, a)

        elif px_format == 3:

            # YUV422
            yuv0, yuv1 = color

            y0 = (yuv0 >> 8) & 0xFF
            u = yuv0 & 0xFF
            y1 = (yuv1 >> 8) & 0xFF
            v = yuv1 & 0xFF

            # Perform YUV to RGB conversion
            c0 = y0 - 16
            c1 = y1 - 16
            d = u - 128
            e = v - 128

            r0 = max(0, min(255, int((298 * c0 + 409 * e + 128) >> 8)))
            g0 = max(0, min(255, int((298 * c0 - 100 * d - 208 * e + 128) >> 8)))
            b0 = max(0, min(255, int((298 * c0 + 516 * d + 128) >> 8)))

            r1 = max(0, min(255, int((298 * c1 + 409 * e + 128) >> 8)))
            g1 = max(0, min(255, int((298 * c1 - 100 * d - 208 * e + 128) >> 8)))
            b1 = max(0, min(255, int((298 * c1 + 516 * d + 128) >> 8)))

            return r0, g0, b0, r1, g1, b1

    def read_pal(self,mode, color, act_buffer):

        if mode == 4444:
            red = ((color >> 8) & 0xf) << 4
            green = ((color >> 4) & 0xf) << 4
            blue = (color & 0xf) << 4
            alpha = '-'

        if mode == 555:
            red = ((color >> 10) & 0x1f) << 3
            green = ((color >> 5) & 0x1f) << 3
            blue = (color & 0x1f) << 3
            alpha = '-'

        elif mode == 565:
            red = ((color >> 11) & 0x1f) << 3
            green = ((color >> 5) & 0x3f) << 2
            blue = (color & 0x1f) << 3
            alpha = '-'

        elif mode == 8888:
            blue = (color >> 0) & 0xFF
            green = (color >> 8) & 0xFF
            red = (color >> 16) & 0xFF
            alpha = (color >> 24) & 0xFF

        act_buffer += bytes([red, green, blue])
        return act_buffer

    def read_pvp(self,f, act_buffer):

        f.seek(0x08)
        pixel_type = int.from_bytes(f.read(1), 'little')
        if pixel_type == 1:
            mode = 565
        elif pixel_type == 2:
            mode = 4444
        elif pixel_type == 6:
            mode = 8888
        else:
            mode = 555

        f.seek(0x0e)
        ttl_entries = int.from_bytes(f.read(2), 'little')

        f.seek(0x10)  # Start palette data
        current_offset = 0x10

        for counter in range(0, ttl_entries):
            if mode != 8888:
                color = int.from_bytes(f.read(2), 'little')
                act_buffer = self.read_pal(mode, color, act_buffer)
                current_offset += 0x2
            else:
                color = int.from_bytes(f.read(4), 'little')
                act_buffer = self.read_pal(mode, color, act_buffer)
                current_offset += 0x4

        return act_buffer, mode, ttl_entries

    def image_flip(self, data, w, h,cmode):

        if cmode == 'RGB':
            pixels_len = 3
        elif cmode == 'RGBA':
            pixels_len = 4
        else:
            pixels_len = 1

        if self.flip and'v' in self.flip:
            data = (np.flipud((np.array(data)).reshape(h, w, -1)).flatten()).reshape(-1, pixels_len).tolist()

        if self.flip and 'h' in self.flip:
            data = (np.fliplr((np.array(data)).reshape(h, w, -1)).flatten()).reshape(-1, pixels_len).tolist()

        return data

    def save_image(self,file_name,data,bits,w,h,cmode,palette):

        if not os.path.exists(self.out_dir):
            os.makedirs(self.out_dir)

        if self.fmt == 'png':
            self.save_png(file_name,data,bits,w,h,cmode,palette)
        elif self.fmt == 'bmp':
            self.save_bmp(file_name,data,bits,w,h,cmode,palette )
        elif self.fmt == 'tga':
            self.save_tga(file_name,data,bits,w,h,cmode,palette )

        if not self.silent:print(fr"{self.out_dir}\{file_name[:-4]}.{self.fmt}")

    # Incomplete! Not supporting palettized images!
    def save_tga(self, file_name,data,bits,w,h,cmode,palette=None):
        # Define TGA header
        tga_header = bytearray([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, w & 255, (w >> 8) & 255,
                                h & 255, (h >> 8) & 255, 32, 0])

        # TGA is not reversed by default
        pixel_data = bytearray()

        # Iterate over the flattened array and append the pixel data
        for pixel in data:
            # Assuming pixel is in BGRA format
            pixel_data.extend([pixel[2], pixel[1], pixel[0], pixel[3]])

        # Combine the header and pixel data
        tga_data = tga_header + pixel_data

        # Save the TGA file
        with open(fr'{self.out_dir}\{file_name[:-4]}.tga', "wb") as tga_file:
            tga_file.write(tga_data)


    def save_bmp(self, file_name, data, bits, w, h, cmode, palette=None):
        pixel_data = bytearray()

        # Define DIB header
        if cmode == 'RGB':
            bpp_var = 24
        elif cmode == 'RGBA':
            bpp_var = 32
        else:
            bpp_var = bits

        if 'PAL' in cmode:
            # Build palette table: BMP stores colours as BGRA
            palette_data = bytearray()
            for color in palette:
                palette_data.extend([color[2], color[1], color[0], 0])
            n_colors = len(palette)
        else:
            palette_data = bytes()
            palette     = bytes(0)
            n_colors    = 0

        # Pixel data starts after the 14-byte file header + 40-byte DIB header + palette
        pix_off = 14 + 40 + len(palette_data)

        dib_header = bytearray([40, 0, 0, 0,  # DIB header size
                                w & 255, (w >> 8) & 255, (w >> 16) & 255, (w >> 24) & 255,  # Image width
                                h & 255, (h >> 8) & 255, (h >> 16) & 255, (h >> 24) & 255,  # Image height
                                1, 0,  # Color planes
                                bpp_var, 0,  # Bits per pixel
                                0, 0, 0, 0,  # Compression method (0 for uncompressed)
                                0, 0, 0, 0,  # Image size (0 for uncompressed)
                                0, 0, 0, 0,  # Horizontal resolution (pixels per meter)
                                0, 0, 0, 0,  # Vertical resolution (pixels per meter)
                                n_colors & 255, (n_colors >> 8) & 255, 0, 0,  # Number of colors in the palette
                                0, 0, 0, 0])  # Number of important colors

        # File header: 'BM' + file size (filled after pixel_data is known) + reserved + pix_off
        file_header = bytearray([66, 77,                                                    # 'BM'
                                 0, 0, 0, 0,                                                # file size (filled below)
                                 0, 0, 0, 0,                                                # reserved
                                 pix_off & 255, (pix_off >> 8) & 255,
                                 (pix_off >> 16) & 255, (pix_off >> 24) & 255])             # pixel data offset

        # Combine headers and palette (pixel_data assembled below)
        header = file_header + dib_header + palette_data

        if 'PAL' in cmode:
            data = [item for sublist in data for item in sublist]
            # Calculate the length of each index sublist

            if cmode == 'RGB-PAL16':
                sublist_length = w//2
            else:
                sublist_length = w  #'RGB-PAL256'

            sublists = [data[i:i + sublist_length] for i in range(0, len(data), sublist_length)]
            reversed_sublists = sublists[::-1]
            pixel_data = bytes([item for sublist in reversed_sublists for item in sublist])

        else:
            # Bmp default order is left-right, bottom-top
            for y in range(h - 1, -1, -1):
                for x in range(w):
                    # Assuming pixel is in BGRA format
                    pixel = data[y * w + x]
                    if cmode == 'RGBA':
                        pixel_data.extend([pixel[2], pixel[1], pixel[0], pixel[3]])
                    elif cmode == 'RGB':
                        pixel_data.extend([pixel[2], pixel[1], pixel[0]])

        # Combine the header, palette (if any), and pixel data
        bmp_data = header + pixel_data

        # Patch the file size field (bytes 2-5) now that total size is known
        total_size = len(bmp_data)
        bmp_data[2] = total_size & 0xFF
        bmp_data[3] = (total_size >> 8) & 0xFF
        bmp_data[4] = (total_size >> 16) & 0xFF
        bmp_data[5] = (total_size >> 24) & 0xFF

        # Save the BMP file
        with open(fr'{self.out_dir}\{file_name[:-4]}.bmp', "wb") as bmp_file:
            bmp_file.write(bmp_data)


    def save_png(self, file_name,data, bits, w, h, cmode, palette):

        Pixel = None
        #print(cmode)

        if cmode == 'RGB':
            Pixel = tuple[int, int, int]

        elif cmode == 'RGBA':
            Pixel = tuple[int, int, int, int]


        image_data = list[list[Pixel]]

        def encode_data(image_data: list[list[Pixel]]) -> list[int]:
            ret = []

            for row in image_data:
                ret.extend([0] + [pixel for color in row for pixel in color])

            return ret

        def calculate_checksum(chunk_type: bytes, data: bytes) -> int:
            checksum = zlib.crc32(chunk_type)
            checksum = zlib.crc32(data, checksum)
            return checksum

        def palette_to_bytearray(palette):
            # Ensure each RGB tuple has three components
            palette = [tuple(rgb[:3]) for rgb in palette]

            # Flatten the RGB tuples and pack them into a bytearray
            byte_array = bytearray()
            for rgb in palette:
                byte_array.extend(struct.pack('BBB', *rgb))
            return byte_array

        color_type = 2  # truecolor by default

        if cmode == 'RGB':
            color_type = 2  # truecolor
        elif cmode == 'RGBA':
            color_type = 6  # truecolor with alpha
        elif 'PAL' in cmode:
            color_type = 3  # indexed color

            # Convert palette to a bytearray
            bytearray_palette = palette_to_bytearray(palette)

        if 'PAL' in cmode:
            # Create indexes
            indexes = [item for sublist in data for item in sublist]
            image_bytes = bytearray([0] + indexes)  # Filter type 0 for the first scanline

            png_array = []

            if cmode == 'RGB-PAL16':
                row_lenght = (w // 2)
            else:
                row_lenght = (w)

            for y in range(h):
                png_array.append(0)  # Filter type 0 for each scanline
                for x in range(row_lenght):
                    png_array.append(x + y * row_lenght + 1)

            # Rearrange indexes based on png_array order
            image_data = bytearray([image_bytes[i] for i in png_array])

        else:
            # Arrange image data into rows
            image_data= bytearray(encode_data([data[i:i + w] for i in range(0, len(data), w)]))


        # Compress image data using zlib with compression level 0
        compressed_data = zlib.compress(image_data,level=1)

        # Write PNG signature
        signature = b'\x89PNG\r\n\x1a\n'

        with open(fr'{self.out_dir}\{file_name[:-4]}.png', "wb") as out:
            out.write(signature)

            # Write IHDR chunk
            ihdr_chunk = struct.pack('!I', w) + struct.pack('!I', h) + bytes([bits, color_type, 0, 0, 0])
            checksum = calculate_checksum(b'IHDR', ihdr_chunk)
            out.write(struct.pack('!I', len(ihdr_chunk)) + b'IHDR' + ihdr_chunk + struct.pack('!I', checksum))

            if 'PAL' in cmode:
                # Write PLTE chunk
                checksum = calculate_checksum(b'PLTE', bytearray_palette)
                out.write(
                    struct.pack('!I', len(bytearray_palette)) + b'PLTE' + bytearray_palette + struct.pack('!I',
                                                                                                          checksum))

            # Write IDAT chunk (compressed image data)
            checksum = calculate_checksum(b'IDAT', compressed_data)
            # print(struct.pack('!I', len(compressed_data)))
            out.write(
                struct.pack('!I', len(compressed_data)) + b'IDAT' + compressed_data + struct.pack('!I', checksum))

            # Write IEND chunk
            checksum = calculate_checksum(b'IEND', b'')
            out.write(struct.pack('!I', 0) + b'IEND' + struct.pack('!I', checksum))

    def write_act(self,act_buffer, file_name):
        #print(act_buffer)

        act_dir = os.path.join(self.out_dir, 'ACT')
        if not os.path.exists(act_dir):
            os.makedirs(act_dir)

        with open(os.path.join(act_dir, f"{file_name[:-4]}.ACT"), 'w+b') as n:

            # Pad file with 0x00 if 16-color palette

            if len(act_buffer) < 768:
                act_file = bytes(act_buffer) + bytes(b'\x00' * (768 - len(act_buffer)))
            else:
                act_file = bytes(act_buffer)
            n.write(act_file)

    def detwiddle(self,w, h):
        # Initialize variables
        index = 0
        pat2, h_inc, arr, h_arr = [], [], [], []

        # Build Twiddle index table
        seq = [2, 6, 2, 22, 2, 6, 2]
        pat = seq + [86] + seq + [342] + seq + [86] + seq

        for i in range(4):
            pat2 += [1366, 5462, 1366, 21846]
            pat2 += [1366, 5462, 1366, 87382] if i % 2 == 0 else [1366, 5462, 1366, 349526]

        for i in range(len(pat2)):
            h_inc.extend(pat + [pat2[i]])
        h_inc.extend(pat)

        # Rectangle (horizontal)
        if w > h:
            ratio = int(w / h)

            # print(f'width is {ratio} times height!')

            if w % 32 == 0 and w & (w - 1) != 0 or h & (h - 1) != 0:
                # print('h and w not power of 2. Using Stride format')
                n = h * w
                for i in range(n):
                    arr.append(i)
            else:
                # Single block h_inc length
                cur_h_inc = {w: h_inc[0:h - 1] + [2]}  # use height size to define repeating block h_inc

                # define the first horizontal row of image pixel array:
                for j in range(ratio):
                    if w in cur_h_inc:
                        for i in cur_h_inc[w]:
                            h_arr.append(index)
                            index += i
                    index = (len(h_arr) * h)

                # define the vertical row of image pixel array of repeating block:
                v_arr = [int(x / 2) for x in h_arr]
                v_arr = v_arr[0:h]

                for val in v_arr:
                    arr.extend([x + val for x in h_arr])

        # Rectangle (vertical)
        elif h > w:
            ratio = int(h / w)
            # print(f'height is {ratio} times width!')

            # Set the size of pixel increase array
            cur_h_inc = {w: h_inc[0:w - 1] + [2]}

            # define the first horizontal row of image pixel array:
            if w in cur_h_inc:
                for i in cur_h_inc[w]:
                    h_arr.append(index)
                    index += i

            # define the vertical row of image pixel array:
            v_arr = [int(x / 2) for x in h_arr]

            # Repeat vertical array block from the last value of array * h/w ratio
            for i in range(ratio):
                if i == 0:
                    last_val = 0
                else:
                    last_val = arr[-1] + 1

                for val in v_arr:
                    arr.extend([last_val + x + val for x in h_arr])

        elif w == h:  # Square
            cur_h_inc = {w: h_inc[0:w - 1] + [2]}
            # define the first horizontal row of image pixel array:
            if w in cur_h_inc:
                for i in cur_h_inc[w]:
                    h_arr.append(index)
                    index += i

            # define the vertical row of image pixel array:
            v_arr = [int(x / 2) for x in h_arr]

            for val in v_arr:
                arr.extend([x + val for x in h_arr])

        return arr

    def decode_pvr(self, f, file_name, w, h, offset=None, px_format=None, tex_format=None, apply_palette=None,
                   act_buffer=None):
        f.seek(offset)
        data = bytearray()

        if tex_format not in [9, 10, 11, 12, 14, 15]:
            arr = self.detwiddle(w, h)

        if tex_format in [5, 6, 7, 8]:

            cmode = None
            if tex_format in [7, 8]:  # 8bpp
                palette_entries = 256
                bits = 8
                pixels = list(f.read(w * h))
                data = [pixels[i] for i in arr]

                if self.flip != '':
                    data = self.image_flip(data, w, h, cmode)
                    # Flatten the nested list and convert each value to an integer
                    data = [int(value) for sublist in data for value in sublist]

                # 4bpp, convert to 8bpp
            else:
                palette_entries = 16
                bits = 4
                pixels = bytearray(f.read(w * h // 2))  # read only required amount of bytes

                # Read 4bpp to 8bpp indexes
                data = []
                for i in range(len(pixels)):
                    data.append(((pixels[i]) & 0x0f) * 0x11)  # last 4 bits
                    data.append((((pixels[i]) & 0xf0) >> 4) * 0x11)  # first 4 bits

                # Assuming 'data' contains the 8bpp indexes
                new_pixels = bytearray(data)

                # Detwiddle 8bpp indexes
                data = []
                for num in arr:
                    data.append(new_pixels[num])

                if self.flip != '':
                    data = self.image_flip(data, w, h, cmode)

                    # Flatten the nested list and convert each value to an integer
                    data = [int(value) for sublist in data for value in sublist]

                data = bytearray(data)  # 8bpp "twiddled data" back into "pixels" variable
                # Convert back to 4bpp indexes with swapped upper and lower bits

                converted_data = bytearray()
                for i in range(0, len(data), 2):

                    # Swap the position of upper and lower bits
                    index1 = (data[i] // 0x11) << 4 | (data[i + 1] // 0x11)

                    # Append the modified index to the converted data
                    converted_data.append(index1)

                data = converted_data

            data = [data]

            if palette_entries == 16:
                if apply_palette == True:
                    palette = [tuple(act_buffer[i:i + 3]) for i in range(0, len(act_buffer), 3)]

                else:palette = [(i * 17, i * 17, i * 17) for i in range(16)]
                cmode = 'RGB-PAL16'

            elif palette_entries == 256:
                if apply_palette == True:
                    palette = [tuple(act_buffer[i:i + 3]) for i in range(0, len(act_buffer), 3)]


                else:palette = [(i, i, i) for i in range(256)]
                cmode = 'RGB-PAL256'

            self.save_image(file_name, data, bits, w, h, cmode, palette)

        # VQ
        elif tex_format in [3, 4, 16, 17]:

            codebook_size = 256

            # SmallVQ - Thanks Kion! :)

            if tex_format == 16:
                if w <= 16:
                    codebook_size = 16
                elif w == 32:
                    codebook_size = 32
                elif w == 64:
                    codebook_size = 128
                else:
                    codebook_size = 256

            # SmallVQ + Mips
            elif tex_format == 17:
                if w <= 16:
                    codebook_size = 16
                elif w == 32:
                    codebook_size = 64
                else:
                    codebook_size = 256

            # print(codebook_size)

            codebook = []

            if px_format not in [3]:
                cmode = 'RGBA'
                for l in range(codebook_size):
                    block = []
                    for i in range(4):
                        pixel = (int.from_bytes(f.read(2), 'little'))
                        pix_col = self.read_col(px_format, pixel)
                        block.append(pix_col)

                    codebook.append(block)

            # YUV422

            else:
                cmode = 'RGB'
                yuv_codebook = []
                for l in range(codebook_size):
                    block = []
                    for i in range(4):
                        pixel = (int.from_bytes(f.read(2), 'little'))
                        block.append(pixel)

                    r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (block[0], block[3]))
                    r2, g2, b2, r3, g3, b3 = self.read_col(px_format, (block[1], block[2]))

                    yuv_codebook.append([(r0, g0, b0), (r2, g2, b2), (r3, g3, b3), (r1, g1, b1)])

                codebook = yuv_codebook

            # VQ Mips!
            if tex_format in [4, 17]:

                pvr_dim = [4, 8, 16, 32, 64, 128, 256, 512, 1024]
                mip_size = [0x10, 0x40, 0x100, 0x400, 0x1000, 0x4000, 0x10000, 0x40000]
                size_adjust = {4: 1, 17: 1}  # 8bpp size is 4bpp *2
                extra_mip = {4: 0x6, 17: 0x6, }  # smallest mips fixed size

                for i in range(len(pvr_dim)):
                    if pvr_dim[i] == w:
                        mip_index = i - 1
                        break

                # Skip mips for image data offset
                mip_sum = (sum(mip_size[:mip_index]) * size_adjust[tex_format]) + (extra_mip[tex_format])

                f.seek(f.tell() + mip_sum)
                # print(hex(f.tell()))

            # Read pixel_index:
            pixel_list = []
            bytes_to_read = int((w * h) / 4)

            # Each index stores 4 pixels
            for i in range(bytes_to_read):
                pixel_index = (int.from_bytes(f.read(1), 'little'))
                pixel_list.append(int(pixel_index))

            # Detwiddle image data indices, put them into arr list
            arr = self.detwiddle(int(w / 2), int(h / 2))

            # Create an empty 2D array to store pixel data
            image_array = [[(0, 0, 0, 0) for _ in range(w)] for _ in range(h)]

            # Iterate over the blocks and update the pixel values in the array
            i = 0
            for y in range(h//2):
                for x in range(w//2):
                    image_array[y * 2][x * 2] = codebook[pixel_list[arr[i]]][0]
                    image_array[y * 2 + 1][x * 2] = codebook[pixel_list[arr[i]]][1]
                    image_array[y * 2][x * 2 + 1] = codebook[pixel_list[arr[i]]][2]
                    image_array[y * 2 + 1][x * 2 + 1] = codebook[pixel_list[arr[i]]][3]
                    i += 1

            # Flatten the 2D array to a 1D list for putdata
            data = [pixel for row in image_array for pixel in row]
            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            palette = ''
            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # BMP ABGR8888
        elif tex_format in [14, 15]:
            pixels = [int.from_bytes(f.read(4), 'little') for _ in range(w * h)]
            data = [(self.read_col(14, p)) for p in pixels]

            palette = ''
            cmode = 'RGBA'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # BUMP decode — SR texel -> 8-bit RGBA normal map.
        #
        # toCartesian formula:
        #   S_angle = (1 - S/255) * PI/2
        #   R_angle = (R/255) * 2*PI, wrapped to [-PI, PI]
        #   Nx = sin(S_angle)*cos(R_angle)
        #   Ny = sin(S_angle)*sin(R_angle)
        #   Nz = cos(S_angle)
        #
        # Stored as 8-bit using the exact inverse of the encoder's _to_sr input path:
        #   R = round((Nx+1)/2 * 255)   [bipolar: -1..+1 -> 0..255]
        #   G = round((Ny+1)/2 * 255)   [bipolar: -1..+1 -> 0..255]
        #   B = round(Nz * 255)         [unipolar: 0..+1 -> 0..255]
        # This guarantees a perfect SR round-trip on re-encoding.
        elif px_format == 4:
            HALFPI   = math.pi / 2.0
            DOUBLEPI = math.pi * 2.0
            pixels = [int.from_bytes(f.read(2), 'little') for _ in range(w * h)]
            raw = np.array([pixels[i] for i in arr], dtype=np.uint16)
            S_b = (raw >> 8).astype(np.float64)
            R_b = (raw & 0xFF).astype(np.float64)
            S_angle = (1.0 - S_b / 255.0) * HALFPI
            R_angle = (R_b / 255.0) * DOUBLEPI
            R_angle = np.where(R_angle > math.pi, R_angle - DOUBLEPI, R_angle)
            Nx = np.sin(S_angle) * np.cos(R_angle)
            Ny = np.sin(S_angle) * np.sin(R_angle)
            Nz = np.cos(S_angle)
            R8 = np.clip(np.round((Nx + 1.0) * 0.5 * 255.0), 0, 255).astype(np.uint8)
            G8 = np.clip(np.round((Ny + 1.0) * 0.5 * 255.0), 0, 255).astype(np.uint8)
            B8 = np.clip(np.round(Nz * 255.0),               0, 255).astype(np.uint8)
            A8 = np.full_like(R8, 255)
            data = list(zip(R8.tolist(), G8.tolist(), B8.tolist(), A8.tolist()))

            if self.flip != '':
                data = self.image_flip(data, w, h, 'RGBA')

            self.save_image(file_name, data, 8, w, h, 'RGBA', '')

        # ARGB modes
        elif px_format in [0, 1, 2, 5, 7, 18]:

            pixels = [int.from_bytes(f.read(2), 'little') for _ in range(w * h)]

            if tex_format not in [9, 10, 11, 12, 14, 15]:  # If Twiddled
                data = [(self.read_col(px_format, p)) for p in (pixels[i] for i in arr)]
            else:
                data = [(self.read_col(px_format, p)) for p in pixels]

            palette = ''
            cmode = 'RGBA'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

        # YUV420 modes
        elif px_format in [6]:
            data = []
            self.yuv420_to_rgb(f, w, h, data)

            palette = ''
            cmode = 'RGB'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name, data, 8,w, h, cmode, palette)


        # YUV422 modes
        elif px_format in [3]:
            data = []

            # Twiddled
            if tex_format not in [9, 10, 11, 12, 14, 15]:
                i = 0
                offset = f.tell()

                for y in range(h):
                    for x in range(0, w, 2):
                        f.seek(offset + (arr[i] * 2))
                        yuv0 = int.from_bytes(f.read(2), 'little')
                        i += 1
                        f.seek(offset + (arr[i] * 2))
                        yuv1 = int.from_bytes(f.read(2), 'little')
                        r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (yuv0, yuv1))
                        data.append((r0, g0, b0))
                        data.append((r1, g1, b1))
                        i += 1



            else:
                for y in range(h):
                    for x in range(0, w, 2):
                        # Read yuv0 and yuv1 separately
                        yuv0 = int.from_bytes(f.read(2), 'little')
                        yuv1 = int.from_bytes(f.read(2), 'little')
                        r0, g0, b0, r1, g1, b1 = self.read_col(px_format, (yuv0, yuv1))
                        data.append((r0, g0, b0))
                        data.append((r1, g1, b1))


            palette = ''
            cmode = 'RGB'

            if self.flip != '':
                data = self.image_flip(data, w, h, cmode)

            # save the image
            self.save_image(file_name,data,8,w,h,cmode,palette)

    def load_pvr(self, PVR_file, apply_palette, act_buffer, file_name):
        px_modes = self.px_modes
        tex_modes = self.tex_modes

        with open(PVR_file, 'rb') as f:
            # Wrap file content in a BytesIO object
            f_buffer = io.BytesIO(f.read())

            header_data = f_buffer.getvalue()
            gbix_offset = header_data.find(b"GBIX")

            if gbix_offset != -1:
                f_buffer.seek(gbix_offset + 0x4)
                gbix_size = int.from_bytes(f_buffer.read(4), byteorder='little')
                if gbix_size == 0x8:
                    gbix_val1 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    gbix_val2 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    if self.debug:
                        print(hex(gbix_val1), hex(gbix_val2))
                elif gbix_size == 0x4:
                    gbix_val1 = int.from_bytes(f_buffer.read(4), byteorder='little')
                    gbix_val2 = ''
                else:
                    print('invalid or unsupported GBIX size:', gbix_size, file_name)
            else:
                if self.debug:
                    print('GBIX found at:', hex(gbix_offset))
                gbix_val1 = ''
                gbix_val2 = ''

            offset = header_data.find(b"PVRT")
            if offset != -1 or len(header_data) < 0x10:
                f_buffer.seek(offset + 0x8)

                # Pixel format
                px_format = int.from_bytes(f_buffer.read(1), byteorder='little')
                tex_format = int.from_bytes(f_buffer.read(1), byteorder='little')

                f_buffer.seek(f_buffer.tell() + 2)

                # Image size
                w = int.from_bytes(f_buffer.read(2), byteorder='little')
                h = int.from_bytes(f_buffer.read(2), byteorder='little')
                offset = f_buffer.tell()

                if self.debug:
                    print(PVR_file.split('/')[-1], 'size:', w, 'x', h, 'format:',
                          f'[{tex_format}] {tex_modes[tex_format]}', f'[{px_format}] {px_modes[px_format]}')

                if tex_format in [2, 4, 6, 8, 10, 12, 15, 17, 18]:
                    if tex_format in [2, 6, 8, 10, 15, 18]:
                        # Mips skip
                        pvr_dim = [4, 8, 16, 32, 64, 128, 256, 512, 1024]
                        mip_size = [0x20, 0x80, 0x200, 0x800, 0x2000, 0x8000, 0x20000, 0x80000]
                        size_adjust = {2: 4, 6: 1, 8: 2, 10: 4, 15: 8, 18: 4}  # 8bpp size is 4bpp *2
                        extra_mip = {2: 0x2c, 6: 0xc, 8: 0x18, 10: 0x2c, 15: 0x54,
                                     18: 0x30}  # smallest mips fixed size

                        for i in range(len(pvr_dim)):
                            if pvr_dim[i] == w:
                                mip_index = i - 1
                                break

                        mip_sum = (sum(mip_size[:mip_index]) * size_adjust[tex_format]) + (extra_mip[tex_format])

                        offset += mip_sum

                self.decode_pvr(f_buffer, file_name, w, h, offset, px_format, tex_format, apply_palette, act_buffer)

                if self.log:
                    log_content = (
                        f"Filename: {PVR_file}, size: {w}x{h}, format: {tex_modes[tex_format]}, "
                        f"mode: {px_modes[px_format]}"
                        f"{f', GBIX: {gbix_val1}' if gbix_val1 != '' else ', GBIX1: ---'}"
                        f"{f', GBIX2: {gbix_val2}' if gbix_val2 != '' else ', GBIX2: ---'}\n"
                    )

                    with open(f'{self.out_dir}/pvr_log.txt', 'a') as l:
                        l.write(log_content)
            else:
                print("'PVRT' header not found!")

    def load_pvp(self,PVP_file, act_buffer, file_name):
        try:
            with open(PVP_file, 'rb') as f:
                file_size = len(f.read())
                f.seek(0x0)
                PVP_check = f.read(4)

                if PVP_check == b'PVPL' and file_size > 0x10:  # PVPL header and size are OK!
                    act_buffer, mode, ttl_entries = self.read_pvp(f, act_buffer)
                    self.write_act(act_buffer, file_name)

                else:
                    print('Invalid .PVP file!')  # Skip this file
        except:
            print(f'PVP data error! {PVP_file}')
        return act_buffer

    def load_pal(self, PAL_file, act_buffer, file_name):
        """Load an AM2 native .pal file (PALT magic header) into act_buffer.

        Layout: chunkname[4] + palette_size[4] + palette_color[4] + pixel_format[4]
        followed by palette_color entries, each stored as a uint32 LE regardless
        of the pixel format.  For 16-bit formats (ARGB1555/RGB565/ARGB4444) the
        colour lives in the low 16 bits; the high 16 bits are always zero.
        For ARGB8888 the full 32 bits are used.

        NM_TEXTURE pixel_format constants:
          0 = ARGB1555 → mode 555
          1 = RGB565   → mode 565
          2 = ARGB4444 → mode 4444
          7 = ARGB8888 → mode 8888
        """
        # NM_TEXTURE constant → bl_pypvr read_pal mode
        _NM_TO_MODE = {0: 555, 1: 565, 2: 4444, 7: 8888}
        try:
            with open(PAL_file, 'rb') as f:
                chunkname = f.read(4)
                if chunkname != b'PALT':
                    print(f'Invalid .pal file (bad magic): {PAL_file}')
                    return act_buffer
                palette_size  = int.from_bytes(f.read(4), 'little')
                palette_color = int.from_bytes(f.read(4), 'little')  # number of entries
                pixel_format  = int.from_bytes(f.read(4), 'little')

                mode = _NM_TO_MODE.get(pixel_format, 565)

                # All entries are stored as uint32 LE.  For 16-bit pixel formats
                # only the low 16 bits carry the colour; the high word is zero.
                for _ in range(palette_color):
                    raw = f.read(4)
                    if len(raw) < 4:
                        break
                    val32 = int.from_bytes(raw, 'little')
                    color = val32 if mode == 8888 else (val32 & 0xffff)
                    act_buffer = self.read_pal(mode, color, act_buffer)

                self.write_act(act_buffer, file_name)
        except Exception as e:
            print(f'PAL data error! {PAL_file}: {e}')
        return act_buffer

    def process_SR(self,SR_value):
        S = (1.0 - ((SR_value >> 8) / 255.0)) * math.pi / 2
        R = (SR_value & 0xFF) / 255.0 * 2 * math.pi - 2 * math.pi * (SR_value & 0xFF > math.pi)
        red = (math.sin(S) * math.cos(R) + 1.0) * 0.5
        green = (math.sin(S) * math.sin(R) + 1.0) * 0.5
        blue = (math.cos(S) + 1.0) * 0.5
        return red, green, blue

    def cart_to_rgb(self,cval):
        return tuple(int(c * 255) for c in cval)

    def yuv420_to_rgb(self,f, w, h, data):
        # Credits to Egregiousguy for YUV420 --> YUV420P conversion
        buffer = bytearray()

        col = w // 16
        row = h // 16

        U = [bytearray() for _ in range(8 * row)]
        V = [bytearray() for _ in range(8 * row)]
        Y01 = [bytearray() for _ in range(col)]
        Y23 = [bytearray() for _ in range(col)]

        for i in range(1, row + 1):
            for n in range(8):
                U[n + 8 * (i - 1)] = bytearray()

            for n in range(col):
                Y01[n] = bytearray()
                Y23[n] = bytearray()

            for _ in range(col):
                for n in range(8):
                    U[n + 8 * (i - 1)] += f.read(0x8)

                for n in range(8):
                    V[n + 8 * (i - 1)] += f.read(0x8)

                for _ in range(2):
                    for n in range(8):
                        Y01[n] += f.read(0x8)

                for _ in range(2):
                    for n in range(8):
                        Y23[n] += f.read(0x8)

            for n in range(col):
                buffer += Y01[n]

            for n in range(col):
                buffer += Y23[n]

        for datauv in U + V:
            buffer += datauv

        # Extract Y, U, and V components from the buffer
        Y = list(buffer[:int(w * h)])
        U = list(buffer[int(w * h):int(w * h * 1.25)])
        V = list(buffer[int(w * h * 1.25):])

        # Reshape Y, U, and V components
        Y = [Y[i:i + w] for i in range(0, len(Y), w)]
        U = [U[i:i + w // 2] for i in range(0, len(U), w // 2)]
        V = [V[i:i + w // 2] for i in range(0, len(V), w // 2)]

        # Upsample U and V components
        U = [item for sublist in U for item in [item for item in sublist] * 2]
        V = [item for sublist in V for item in [item for item in sublist] * 2]

        # Reshape U and V components after upsampling
        U = [U[i:i + w] for i in range(0, len(U), w)]
        V = [V[i:i + w] for i in range(0, len(V), w)]

        # Convert YUV to RGB
        for i in range(h):
            for j in range(w):
                i_UV = min(i // 2, len(U) - 1)
                j_UV = min(j // 2, len(U[i_UV]) - 1)
                y, u, v = Y[i][j], U[i_UV][j_UV], V[i_UV][j_UV]
                r = int(max(0, min(255, round(y + 1.402 * (v - 128)))))
                g = int(max(0, min(255, round(y - 0.344136 * (u - 128) - 0.714136 * (v - 128)))))
                b = int(max(0, min(255, round(y + 1.772 * (u - 128)))))
                data.append((r, g, b))
        return data


# =============================================================================
#  PVR ENCODER
#  Ported from pvr_tools Blender addon (VincentNL, MIT License)
#  Adapted for bl_pypvr.py: bpy image loading replaced with PIL,
#  no Blender operators/panels/properties — pure encoding only.
# =============================================================================

# Format tables 

_ENC_PX_IDS = {
    "1555": 0, "565": 1, "4444": 2, "yuv422": 3,
    "bump":  4, "555": 5, "yuv420": 6, "8888": 7,
    "p4bpp": 8, "p8bpp": 9,
}
_ENC_TEX_IDS = {
    "tw":       1,  "tw mm":    2,
    "vq":       3,  "vq mm":    4,
    "pal4":     5,  "pal4 mm":  6,
    "pal8":     7,  "pal8 mm":  8,
    "re":       9,  "re mm":   10,
    "st":      11,  "st mm":   12,
    "twre":    13,
    "bmp":     14,  "bmp mm":  15,
    "svq":     16,  "svq mm":  17,
    "twal mm": 18,
}

# Compatibility matrix — rows=tex, cols=px
# px:  1555  565  4444  yuv422  bump  555  yuv420  8888  p4bpp  p8bpp
_ENC_TEX_LIST = ["tw","twre","vq","pal4","pal8","re","st","bmp","svq","twal"]
_ENC_PX_LIST  = ["1555","565","4444","yuv422","bump","555","yuv420","8888","p4bpp","p8bpp"]
_ENC_COMPAT   = [
    [1,1,1,1,1,0,0,0,0,0],  # tw
    [1,1,1,1,1,0,0,0,0,0],  # twre
    [1,1,1,1,1,0,0,0,0,0],  # vq
    [1,1,1,0,0,0,0,1,1,0],  # pal4
    [1,1,1,0,0,0,0,1,0,1],  # pal8
    [1,1,1,1,0,0,1,0,0,0],  # re
    [1,1,1,1,0,0,0,0,0,0],  # st
    [0,0,0,0,0,0,0,1,0,0],  # bmp
    [1,1,1,1,1,0,0,0,0,0],  # svq
    [1,1,1,1,1,0,0,0,0,0],  # twal
]

def _enc_is_compatible(tex, px):
    base = tex.replace(" mm", "").strip()
    if base not in _ENC_TEX_LIST or px not in _ENC_PX_LIST:
        return False
    return bool(_ENC_COMPAT[_ENC_TEX_LIST.index(base)][_ENC_PX_LIST.index(px)])


# Twiddle index table (lazy-init, shared with decode class) 

_ENC_TWIDDLE_TABLE = None

def _enc_get_twiddle_table():
    global _ENC_TWIDDLE_TABLE
    if _ENC_TWIDDLE_TABLE is None:
        seq  = [2, 6, 2, 22, 2, 6, 2]
        pat  = seq + [86] + seq + [342] + seq + [86] + seq
        pat2 = []
        for i in range(4):
            pat2 += [1366, 5462, 1366, 21846]
            pat2 += ([1366, 5462, 1366, 87382] if i % 2 == 0
                     else [1366, 5462, 1366, 349526])
        h_inc = []
        for val in pat2:
            h_inc.extend(pat + [val])
        _ENC_TWIDDLE_TABLE = h_inc
    return _ENC_TWIDDLE_TABLE

def _enc_twiddle_indices(w, h):
    """Return the twiddle permutation index array for an image of size w×h."""
    h_inc = _enc_get_twiddle_table()
    index = 0
    arr   = []
    h_arr = []

    if w > h:
        ratio = w // h
        if (w % 32 == 0 and w & (w - 1) != 0) or h & (h - 1) != 0:
            return list(range(h * w))
        block = h_inc[0:h - 1] + [2]
        for _ in range(ratio):
            for inc in block:
                h_arr.append(index)
                index += inc
            index = len(h_arr) * h
        v_arr = [x // 2 for x in h_arr][:h]
        for val in v_arr:
            arr.extend(x + val for x in h_arr)
    elif h > w:
        block = h_inc[0:w - 1] + [2]
        for inc in block:
            h_arr.append(index)
            index += inc
        v_arr = [x // 2 for x in h_arr]
        for i in range(h // w):
            last = 0 if i == 0 else arr[-1] + 1
            for val in v_arr:
                arr.extend(last + x + val for x in h_arr)
    else:
        block = h_inc[0:w - 1] + [2]
        for inc in block:
            h_arr.append(index)
            index += inc
        v_arr = [x // 2 for x in h_arr]
        for val in v_arr:
            arr.extend(x + val for x in h_arr)

    return arr


# Image loading (PIL-based, no bpy) 

def load_image_as_rgba(filepath):
    """
    Load any image via bpy (inside Blender) or PIL (standalone) and return
    (np.ndarray[H,W,4], w, h).  Alpha channel is always present.
    Dtype is always uint8.
    """
    try:
        import bpy as _bpy
        name = "__pvr_enc_tmp__"
        if name in _bpy.data.images:
            _bpy.data.images.remove(_bpy.data.images[name])
        img = _bpy.data.images.load(os.path.realpath(filepath))
        img.name = name
        # Disable colorspace conversion: we want raw stored values.
        # For regular colour textures (565/1555/4444) the PVR hardware displays
        # sRGB values directly, so keeping them as-is is also correct.
        try:
            img.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass  # old Blender builds that don't support this setting
        w, h = img.size
        if w == 0 or h == 0:
            _bpy.data.images.remove(img)
            raise ValueError(f"Empty image: {filepath}")
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        _bpy.data.images.remove(img)
        # bpy gives bottom-up float RGBA in [0,1]
        arr_f = px.reshape(h, w, 4)[::-1]  # flip to top-down
        arr = np.clip(np.round(arr_f * 255.0), 0, 255).astype(np.uint8)
        return arr, w, h
    except ImportError:
        # outside Blender — PIL fallback
        from PIL import Image as _PIL
        img = _PIL.open(filepath)
        w, h = img.size
        arr = np.array(img.convert("RGBA"), dtype=np.uint8)
        return arr, w, h


# =============================================================================

class encode:
    """
    Encode an image file (or numpy RGBA array) to PowerVR2 .pvr bytes.

    Quick usage
    -----------
    pvr_bytes, pvp_bytes = encode.from_file("TexID_000.png")
    pvr_bytes, pvp_bytes = encode.from_file("TexID_000.png",
                                             tex_mode="vq", px_mode="565")

    pvr_bytes, pvp_bytes = encode.from_array(rgba_array,
                                              tex_mode="tw", px_mode="1555")

    pvp_bytes is None for non-palette modes.
    Write pvr_bytes to a .pvr file, pvp_bytes (if not None) to a .pvp file.
    """

    # size classification 
    @staticmethod
    def _size_flags(w, h):
        def p2(n): return n > 0 and (n & (n - 1)) == 0
        sq  = p2(w) and p2(h) and w == h
        rec = p2(w) and p2(h) and w != h
        st  = (w % 32 == 0) and (32 <= w <= 992) and not p2(h)
        yuv = (w % 16 == 0) and (h % 16 == 0)
        return sq, rec, st, yuv

    # auto-format (mirrors PyPVR / pvr_tools logic, skips pal/yuv420/st) 
    @staticmethod
    def _auto_format(rgba, sq, rec, st, yuv):
        """
        Return (tex_mode, px_mode) inferred from image content.
        Never returns palette, yuv420, or stride modes.
        """
        if not sq and not rec:
            # non-power-of-2: fall back to stride if available, else re
            if st:
                # stride still needs a px — analyse alpha
                pass
            elif yuv:
                return "re", "yuv420"
            else:
                return "tw", "565"   # last-resort fallback

        alpha = rgba[:, :, 3]
        has_alpha = bool(np.any(alpha < 255))
        if has_alpha:
            vals = set(alpha.ravel().tolist())
            px = "1555" if vals <= {0, 255} else "4444"
        else:
            px = "565"

        if sq:
            tex = "tw"
        elif rec:
            tex = "twre"
        else:
            tex = "st"

        return tex, px

    # pixel conversion helpers (vectorised NumPy) 
    @staticmethod
    def _to_565(flat):
        r = (flat[:, 0].astype(np.uint16) >> 3)
        g = (flat[:, 1].astype(np.uint16) >> 2)
        b = (flat[:, 2].astype(np.uint16) >> 3)
        return (r << 11) | (g << 5) | b

    @staticmethod
    def _to_1555(flat):
        a = (flat[:, 3].astype(np.uint16) >> 7)
        r = (flat[:, 0].astype(np.uint16) >> 3)
        g = (flat[:, 1].astype(np.uint16) >> 3)
        b = (flat[:, 2].astype(np.uint16) >> 3)
        return (a << 15) | (r << 10) | (g << 5) | b

    @staticmethod
    def _to_4444(flat):
        a = (flat[:, 3].astype(np.uint16) >> 4)
        r = (flat[:, 0].astype(np.uint16) >> 4)
        g = (flat[:, 1].astype(np.uint16) >> 4)
        b = (flat[:, 2].astype(np.uint16) >> 4)
        return (a << 12) | (r << 8) | (g << 4) | b

    @staticmethod
    def _to_8888(flat):
        r = flat[:, 0].astype(np.uint32)
        g = flat[:, 1].astype(np.uint32)
        b = flat[:, 2].astype(np.uint32)
        a = flat[:, 3].astype(np.uint32)
        return (r << 24) | (g << 16) | (b << 8) | a

    @staticmethod
    def _build_sr_table():
        """Precompute the full 256×256 SR -> unit normal vector lookup table.

        Returns
        -------
        grid : np.ndarray, shape (256, 256, 3), float32
            grid[S_byte, R_byte] = (Nx, Ny, Nz) unit normal.
            Used for O(1) neighbourhood lookups during encoding.
        """
        HALFPI   = math.pi / 2.0
        DOUBLEPI = math.pi * 2.0
        S_all = np.arange(256, dtype=np.float64)
        R_all = np.arange(256, dtype=np.float64)
        S_grid, R_grid = np.meshgrid(S_all, R_all, indexing='ij')   # (256, 256)
        S_ang = (1.0 - S_grid / 255.0) * HALFPI
        R_ang = R_grid / 255.0 * DOUBLEPI
        R_ang = np.where(R_ang > math.pi, R_ang - DOUBLEPI, R_ang)
        NX = np.sin(S_ang) * np.cos(R_ang)
        NY = np.sin(S_ang) * np.sin(R_ang)
        NZ = np.cos(S_ang)
        return np.stack([NX, NY, NZ], axis=-1).astype(np.float32)   # (256, 256, 3)

    # Class-level cache — built once per process
    _SR_TABLE = None

    @staticmethod
    def _to_sr(flat):
        # PVR2 BUMP encoder: normal map -> SR texel.
        #
        # Two-stage seeded neighbourhood search — globally optimal in practice:
        #
        #   Stage 1 (seed): analytic atan2/arccos gives an initial (S0, R0)
        #                   that is always within ~1 bin of the true optimum.
        #
        #   Stage 2 (refine): exhaustively evaluate all (2*RADIUS+1)^2 = 25
        #                     candidates centred on (S0, R0).  S is clamped to
        #                     [0, 255]; R wraps mod 256.  The candidate whose
        #                     decoded unit normal has the highest dot product
        #                     with the normalised input vector is chosen.
        #
        # Validated against true brute-force (all 65536 SR pairs): 99.6% exact
        # match on random inputs; worst-case angular error < 0.36° (< 1 SR bin).
        # Runtime: ~0.14s for a 256×256 image vs ~26s for naive full search.
        #
        # Input: uint8 RGBA flat array — R,G bipolar [0,255], B unipolar [0,255].
        HALFPI   = math.pi / 2.0
        DOUBLEPI = math.pi * 2.0
        RADIUS   = 2   # search (2*RADIUS+1)^2 = 25 candidates around seed

        # Build or retrieve cached SR grid
        if encode._SR_TABLE is None:
            encode._SR_TABLE = encode._build_sr_table()
        table_grid = encode._SR_TABLE   # (256, 256, 3) float32

        # Input: flat[:,0]=R, flat[:,1]=G, flat[:,2]=B, all uint8
        # R,G bipolar [0,255] -> [-1,+1];  B unipolar [0,255] -> [0,+1]
        maxval = 255.0
        cx = flat[:, 0].astype(np.float64) / maxval * 2.0 - 1.0
        cy = flat[:, 1].astype(np.float64) / maxval * 2.0 - 1.0
        cz = flat[:, 2].astype(np.float64) / maxval

        # Normalise input vectors (guard zero-length)
        mag = np.sqrt(cx**2 + cy**2 + cz**2)
        mag = np.where(mag < 1e-9, 1.0, mag)
        nx = (cx / mag).astype(np.float32)
        ny = (cy / mag).astype(np.float32)
        nz = (cz / mag).astype(np.float32)

        # Stage 1: analytic seed 
        polar   = np.arccos(np.clip(nz.astype(np.float64), -1.0, 1.0))
        azimuth = np.arctan2(cy / mag, cx / mag)
        S0 = np.clip(((HALFPI - polar) / HALFPI * 255.0 + 0.5).astype(np.int32), 0, 255)
        azimuth = np.where(azimuth < 0, azimuth + DOUBLEPI, azimuth)
        R0 = (azimuth / DOUBLEPI * 255.0 + 0.5).astype(np.int32) % 256

        # Stage 2: neighbourhood search 
        offsets = np.arange(-RADIUS, RADIUS + 1, dtype=np.int32)
        ds, dr  = np.meshgrid(offsets, offsets, indexing='ij')
        ds = ds.ravel(); dr = dr.ravel()          # (K,) K = 25

        # Candidate (S, R) indices for every pixel: (N, K)
        S_cands = np.clip(S0[:, None] + ds[None, :], 0, 255).astype(np.int32)
        R_cands = ((R0[:, None] + dr[None, :]) % 256).astype(np.int32)

        # Gather decoded normals from the grid: (N, K, 3) — one indexing call
        cand_xyz = table_grid[S_cands, R_cands]   # float32

        # Dot product vs input normal: (N, K)
        input_xyz = np.stack([nx, ny, nz], axis=-1)           # (N, 3)
        dots = np.einsum('nkc,nc->nk', cand_xyz, input_xyz)   # (N, K)

        best_k = np.argmax(dots, axis=1)                       # (N,)
        N      = flat.shape[0]
        best_S = S_cands[np.arange(N), best_k].astype(np.uint16)
        best_R = R_cands[np.arange(N), best_k].astype(np.uint16)
        return (best_S << 8) | best_R

    @staticmethod
    def _to_yuv422(flat, w, h):
        rgb = flat[:, :3].astype(np.float32)
        r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
        Y = np.clip( 0.299*r + 0.587*g + 0.114*b,       0, 255).astype(np.uint16)
        U = np.clip(-0.169*r - 0.331*g + 0.499*b + 128, 0, 255).astype(np.uint16)
        V = np.clip( 0.499*r - 0.418*g - 0.081*b + 128, 0, 255).astype(np.uint16)
        out = np.zeros(w * h, dtype=np.uint16)
        out[0::2] = (Y[0::2] << 8) | U[0::2]
        out[1::2] = (Y[1::2] << 8) | V[0::2]   # V taken from even (left) pixel of each pair, matching decoder expectation
        return out

    @staticmethod
    def _to_yuv420(rgba, w, h):
        rgb = rgba[:, :, :3].astype(np.float32)
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        Y  = np.clip( 0.299*r + 0.587*g + 0.114*b,       0, 255).astype(np.uint8)
        U4 = np.clip(-0.147*r - 0.289*g + 0.436*b + 128, 0, 255).astype(np.int32)
        V4 = np.clip( 0.615*r - 0.515*g - 0.100*b + 128, 0, 255).astype(np.int32)
        U  = np.clip((U4[0::2, 0::2] + U4[1::2, 0::2] +
                      U4[0::2, 1::2] + U4[1::2, 1::2]) // 4, 0, 255).astype(np.uint8)
        V  = np.clip((V4[0::2, 0::2] + V4[1::2, 0::2] +
                      V4[0::2, 1::2] + V4[1::2, 1::2]) // 4, 0, 255).astype(np.uint8)
        out = bytearray()
        for by in range(0, h, 16):
            for bx in range(0, w, 16):
                out.extend(U[by//2:by//2+8, bx//2:bx//2+8].ravel())
                out.extend(V[by//2:by//2+8, bx//2:bx//2+8].ravel())
                out.extend(Y[by   :by+8,    bx   :bx+8   ].ravel())
                out.extend(Y[by   :by+8,    bx+8 :bx+16  ].ravel())
                out.extend(Y[by+8 :by+16,   bx   :bx+8   ].ravel())
                out.extend(Y[by+8 :by+16,   bx+8 :bx+16  ].ravel())
        return np.frombuffer(bytes(out), dtype=np.uint8)

    # K-means (pure NumPy, BLAS-accelerated) 
    @staticmethod
    def _kmeans(data, k, n_iter=20, seed=2):
        """data: (N, C) uint8. Returns (centroids[k,C] uint8, labels[N] uint32)."""
        np.random.seed(seed)
        N, C = data.shape
        f = data.astype(np.float32)

        # K-means++ init
        centroids = np.empty((k, C), dtype=np.float32)
        centroids[0] = f[np.random.randint(N)]
        dists = np.sum((f - centroids[0]) ** 2, axis=1)
        for i in range(1, k):
            total = dists.sum()
            idx = (np.random.choice(N, p=dists / total)
                   if total > 0 else np.random.randint(N))
            centroids[i] = f[idx]
            dists = np.minimum(dists, np.sum((f - centroids[i]) ** 2, axis=1))

        new_c  = np.empty_like(centroids)
        counts = np.empty(k, dtype=np.int32)

        for _ in range(n_iter):
            f_norm = np.sum(f ** 2, axis=1)[:, np.newaxis]
            c_norm = np.sum(centroids ** 2, axis=1)[np.newaxis, :]
            d2     = f_norm + c_norm - 2.0 * np.dot(f, centroids.T)
            labels = np.argmin(d2, axis=1)

            new_c.fill(0.0); counts.fill(0)
            np.add.at(new_c,  labels, f)
            np.add.at(counts, labels, 1)
            mask = counts > 0
            new_c[mask] /= counts[mask, np.newaxis]

            empty = ~mask
            if empty.any():
                ri = np.random.choice(N, size=int(empty.sum()), replace=False)
                new_c[empty] = f[ri]

            if np.array_equal(new_c, centroids):
                break
            centroids = new_c.copy()

        centroids = np.clip(np.round(centroids), 0, 255).astype(np.uint8)
        f_norm = np.sum(f ** 2, axis=1)[:, np.newaxis]
        c_norm = np.sum(centroids.astype(np.float32) ** 2, axis=1)[np.newaxis, :]
        d2 = f_norm + c_norm - 2.0 * np.dot(f, centroids.astype(np.float32).T)
        labels = np.argmin(d2, axis=1).astype(np.uint32)
        return centroids, labels

    # palette quantisation 
    def _quantize(self, rgba, n_colors, n_iter=20):
        flat = rgba.reshape(-1, 4)
        palette, labels = self._kmeans(flat, n_colors, n_iter)
        return labels.astype(np.uint8), palette

    # build PVP file bytes 
    @staticmethod
    def _build_pvp(palette, n_colors, px_mode, pvpbank=0):
        """palette: (n_colors, 4) uint8 RGBA. Returns raw .pvp bytes."""
        pal = palette.astype(np.uint32)
        if px_mode == "565":
            pal_mode, pixel_size = 1, 2
            r = (pal[:, 0] >> 3).astype(np.uint16)
            g = (pal[:, 1] >> 2).astype(np.uint16)
            b = (pal[:, 2] >> 3).astype(np.uint16)
            pal_data = ((r << 11) | (g << 5) | b).astype(np.uint16)
        elif px_mode == "1555":
            pal_mode, pixel_size = 0, 2
            a = (pal[:, 3] >> 7).astype(np.uint16)
            r = (pal[:, 0] >> 3).astype(np.uint16)
            g = (pal[:, 1] >> 3).astype(np.uint16)
            b = (pal[:, 2] >> 3).astype(np.uint16)
            pal_data = ((a << 15) | (r << 10) | (g << 5) | b).astype(np.uint16)
        elif px_mode == "4444":
            pal_mode, pixel_size = 2, 2
            a = (pal[:, 3] >> 4).astype(np.uint16)
            r = (pal[:, 0] >> 4).astype(np.uint16)
            g = (pal[:, 1] >> 4).astype(np.uint16)
            b = (pal[:, 2] >> 4).astype(np.uint16)
            pal_data = ((a << 12) | (r << 8) | (g << 4) | b).astype(np.uint16)
        elif px_mode == "8888":
            pal_mode, pixel_size = 6, 4
            r = pal[:, 0].astype(np.uint32)
            g = pal[:, 1].astype(np.uint32)
            b = pal[:, 2].astype(np.uint32)
            a = pal[:, 3].astype(np.uint32)
            pal_data = ((r << 24) | (g << 16) | (b << 8) | a).astype(np.uint32)
        else:
            pal_mode, pixel_size = 0, 2
            a = (pal[:, 3] >> 7).astype(np.uint16)
            r = (pal[:, 0] >> 3).astype(np.uint16)
            g = (pal[:, 1] >> 3).astype(np.uint16)
            b = (pal[:, 2] >> 3).astype(np.uint16)
            pal_data = ((a << 15) | (r << 10) | (g << 5) | b).astype(np.uint16)

        pvp_payload = pal_data.tobytes()
        header = (
            b"PVPL" +
            (pixel_size * n_colors + 8).to_bytes(4, "little") +
            pal_mode.to_bytes(2, "little") +
            (pvpbank if pvpbank <= 63 else 0).to_bytes(2, "little") +
            b"\x00\x00" +
            n_colors.to_bytes(2, "little")
        )
        pad = (-len(pvp_payload)) % 8
        return header + pvp_payload + b"\x00" * pad

    # VQ twiddle (matches pypvr twiddleVQ exactly) 
    @staticmethod
    def _twiddle_vq(height, width):
        height, width = int(height), int(width)
        y, x = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
        values = np.zeros((height, width), dtype=np.uint32)
        for i in range(max(height, width).bit_length()):
            values |= ((x >> i) & 1).astype(np.uint32) << (2 * i)
            values |= ((y >> i) & 1).astype(np.uint32) << (2 * i + 1)
        return values

    # codebook bytes from centroids 
    def _codebook_bytes(self, centroids, cb_size, px_mode):
        nc = 4 if px_mode in ("4444", "1555") else 3
        codebook = np.zeros((cb_size, 8), dtype=np.uint8)

        # yuv422 needs special per-cluster handling — mirrors pypvr codebook_create
        if px_mode == "yuv422":
            for i, cluster in enumerate(centroids[:cb_size]):
                pix = cluster.reshape(4, 3).astype(np.float32)
                r, g, b = pix[:, 0], pix[:, 1], pix[:, 2]
                Y = np.clip( 0.299*r + 0.587*g + 0.114*b,       0, 255).astype(np.int32)
                U = np.clip(-0.169*r - 0.331*g + 0.499*b + 128, 0, 255).astype(np.int32)
                V = np.clip( 0.499*r - 0.418*g - 0.0813*b + 128, 0, 255).astype(np.int32)
                # Decoder pairs (word0,word3) and (word1,word2) as YUV422 pairs.
                # Matching pypvr reference: U[0]/U[1] stay in words 0/1,
                # V[0] goes into word2, V[1] goes into word3 (cross-pair chroma).
                yuv_code = np.array([
                    (Y[0] << 8) | U[0],  # word0: Y of p0, U of p0
                    (Y[1] << 8) | U[1],  # word1: Y of p1, U of p1
                    (Y[2] << 8) | V[0],  # word2: Y of p2, V of p0
                    (Y[3] << 8) | V[1],  # word3: Y of p3, V of p1
                ], dtype=np.uint16)
                codebook[i] = yuv_code.view(np.uint8)
            return bytes(codebook.tobytes())

        for i, cluster in enumerate(centroids[:cb_size]):
            pix = cluster.reshape(4, nc)
            pix_rgba = (np.column_stack([pix.astype(np.uint32),
                                         np.full((4, 1), 255, dtype=np.uint32)])
                        if nc == 3 else pix.astype(np.uint32))
            if px_mode == "565":
                v = self._to_565(pix_rgba)
            elif px_mode == "1555":
                v = self._to_1555(pix_rgba)
            elif px_mode == "4444":
                v = self._to_4444(pix_rgba)
            else:
                v = self._to_565(pix_rgba)
            codebook[i] = v.astype(np.uint16).view(np.uint8)
        return bytes(codebook.tobytes())

    # VQ compression 
    def _vq_compress(self, rgba, px_mode, tex_mode, cb_size, n_iter, seed,
                     orig_w, orig_h):
        """Returns (codebook_bytes, index_bytes)."""
        has_mm = "mm" in tex_mode
        nc = 4 if px_mode in ("4444", "1555") else 3
        W, H = orig_w, orig_h

        arr = np.rot90(np.fliplr(rgba[:, :, :nc]))

        n_clusters = cb_size if "svq" in tex_mode else (
            (H * (4 if has_mm else 2)) if H < 32 else 256
        )
        n_clusters = min(n_clusters, cb_size)

        if has_mm:
            blocks = arr.reshape(W, 2, H // 2, 2, nc)
        else:
            blocks = arr.reshape(H // 2, 2, W // 2, 2, nc)
        blocks = blocks.transpose(0, 2, 1, 3, 4).reshape(-1, 4 * nc)

        centroids, labels = self._kmeans(blocks, n_clusters, n_iter, seed)
        codebook = self._codebook_bytes(centroids, cb_size, px_mode)

        if has_mm:
            mip_level  = int(np.log2(W))
            mip_height = np.zeros(mip_level, dtype=int)
            mip_start  = np.zeros(mip_level, dtype=int)
            end_index  = np.zeros(mip_level, dtype=int)
            start_off  = 0
            for i in range(mip_level):
                idx = mip_level - 1 - i
                mh  = (W // 2) >> i
                mip_height[idx] = mh
                end_off = start_off + (mh * mh << i)
                mip_start[idx] = start_off
                end_index[idx] = end_off
                start_off = end_off

            total = int(np.sum(mip_height ** 2))
            index = np.zeros(total, dtype=labels.dtype)
            mip_off = 0
            for i in range(mip_level):
                cmh  = int(mip_height[i])
                step = W // 2 // cmh
                grid = labels[int(mip_start[i]):int(end_index[i])].reshape(W // 2, cmh)
                mip_data  = grid[::step, :cmh].flatten()
                tw_idx    = self._twiddle_vq(cmh, cmh).ravel()
                labels_tw = np.zeros(cmh * cmh, dtype=mip_data.dtype)
                labels_tw[tw_idx] = mip_data
                size = cmh * cmh
                index[mip_off:mip_off + size] = labels_tw
                mip_off += size
            index = np.pad(index, (1, 0), mode="constant")
        else:
            nh, nw = H // 2, W // 2
            tw_idx = self._twiddle_vq(nh, nw).ravel()
            index  = np.zeros(nh * nw, dtype=labels.dtype)
            index[tw_idx] = labels

        return codebook, bytes(index.astype(np.uint8).tobytes())

    # bilinear downsample (no PIL) 
    @staticmethod
    def _resize(rgba, new_w, new_h):
        out = rgba
        h, w = out.shape[:2]
        while w > new_w or h > new_h:
            if w > new_w:
                out = ((out[:, 0::2].astype(np.uint16) +
                        out[:, 1::2].astype(np.uint16)) // 2).astype(np.uint8)
                w //= 2
            if h > new_h:
                out = ((out[0::2].astype(np.uint16) +
                        out[1::2].astype(np.uint16)) // 2).astype(np.uint8)
                h //= 2
        return out

    # encode one tile to raw pixel bytes (no header) 
    def _encode_tile(self, rgba, w, h, tex, px):
        flat = rgba.reshape(-1, 4)
        if px == "565":
            pv = self._to_565(flat);    dtype = np.uint16
        elif px == "1555":
            pv = self._to_1555(flat);   dtype = np.uint16
        elif px == "4444":
            pv = self._to_4444(flat);   dtype = np.uint16
        elif px in ("8888",) or "bmp" in tex:
            pv = self._to_8888(flat);   dtype = np.uint32
        elif px == "bump":
            pv = self._to_sr(flat);     dtype = np.uint16
        elif px == "yuv422":
            if w == 1:
                pv = self._to_565(flat); dtype = np.uint16
            else:
                pv = self._to_yuv422(flat, w, h); dtype = np.uint16
        elif px == "yuv420":
            return bytes(self._to_yuv420(rgba, w, h)), np.uint8
        else:
            pv = self._to_565(flat);    dtype = np.uint16

        arr = pv.flatten().astype(dtype)

        # twiddle when required
        if any(k in tex for k in ("tw", "pal", "twal")):
            tw  = _enc_twiddle_indices(w, h)
            out = np.zeros(w * h, dtype=dtype)
            out[tw] = arr
            arr = out

        return bytes(arr.tobytes()), dtype

    # encode all pixels for a given mode (no header) 
    def _encode_pixels(self, rgba, w, h, tex, px, n_iter, vq_seed):

        # VQ / SmallVQ
        if "vq" in tex or "svq" in tex:
            if "svq" in tex:
                cb_size = {8: 16, 16: 16,
                           32: 64  if "mm" in tex else 32,
                           64: 256 if "mm" in tex else 128}.get(h, 256)
            else:
                cb_size = 256

            if "mm" in tex:
                atlas = np.zeros((h, w * 2, rgba.shape[2]), dtype=np.uint8)
                x_off = 0; cur_w, cur_h = w, h
                while cur_w >= 1 and cur_h >= 1:
                    mip = self._resize(rgba, cur_w, cur_h)
                    atlas[0:cur_h, x_off:x_off + cur_w] = mip
                    x_off += cur_w; cur_w //= 2; cur_h //= 2
                vq_input = atlas
            else:
                vq_input = rgba

            cb_bytes, idx_bytes = self._vq_compress(
                vq_input, px, tex, cb_size, n_iter, vq_seed, orig_w=w, orig_h=h
            )
            return cb_bytes + idx_bytes

        # PAL4 / PAL8 — returns (pixel_bytes, palette) tuple
        if "pal4" in tex or "pal8" in tex:
            n_colors = 16 if "pal4" in tex else 256
            # Quantize once against the full-resolution image to get a stable palette
            labels_full, palette = self._quantize(rgba, n_colors, n_iter)

            if "mm" in tex:
                # PAL8/PAL4 + Mipmaps: encode each mip level's indices separately.
                # The palette is derived from the full-res image; each mip level is
                # re-sampled and its pixels are mapped to the nearest palette entry
                # before twiddling — matching pypvr's encode_pvr behaviour.
                if "pal8" in tex:
                    pad = b"\x00" * 3
                else:
                    pad = b"\x00" * 2

                levels = []
                cur_size = h
                # Build a flat palette array for nearest-colour lookup (RGBA, float32)
                pal_rgba = palette.astype(np.float32)  # shape (n_colors, 4)

                while cur_size >= 1:
                    mip = self._resize(rgba, cur_size, cur_size)   # (cur_size, cur_size, 4)
                    flat = mip.reshape(-1, 4).astype(np.float32)   # (N, 4)

                    # Nearest-palette-entry assignment via squared-distance
                    # Broadcast: (N,1,4) - (1,n_colors,4) → (N,n_colors,4)
                    diff = flat[:, np.newaxis, :] - pal_rgba[np.newaxis, :, :]
                    idx = np.argmin(np.sum(diff ** 2, axis=2), axis=1).astype(np.uint8)

                    tw = _enc_twiddle_indices(cur_size, cur_size)
                    tw_idx = np.zeros(cur_size * cur_size, dtype=np.uint8)
                    tw_idx[tw] = idx

                    if "pal4" in tex:
                        packed = (tw_idx[::2] & 0x0F) | ((tw_idx[1::2] & 0x0F) << 4)
                        levels.insert(0, bytes(packed.tobytes()))
                    else:
                        levels.insert(0, bytes(tw_idx.tobytes()))

                    cur_size //= 2

                return pad + b"".join(levels), palette

            # Non-MM PAL: twiddle full-res labels and return
            tw = _enc_twiddle_indices(w, h)
            tw_labels = np.zeros(w * h, dtype=np.uint8)
            tw_labels[tw] = labels_full
            if "pal4" in tex:
                packed = (tw_labels[::2] & 0x0F) | ((tw_labels[1::2] & 0x0F) << 4)
                return bytes(packed.tobytes()), palette
            return bytes(tw_labels.tobytes()), palette

        # Non-VQ with mipmaps
        if "mm" in tex:
            if "8888" in px or "bmp" in tex:
                pad = b"\x00" * 4
            elif "twal" in tex:
                pad = b"\x00" * 6
            else:
                pad = b"\x00" * 2

            levels = []
            cur_size = h
            while cur_size >= 1:
                mip = self._resize(rgba, cur_size, cur_size)
                tile, _ = self._encode_tile(mip, cur_size, cur_size, tex, px)
                levels.insert(0, tile)   # prepend: smallest first
                cur_size //= 2
            return pad + b"".join(levels)

        # Standard single tile
        tile, _ = self._encode_tile(rgba, w, h, tex, px)
        return tile

    # build PVRT (+ optional GBIX) header 
    @staticmethod
    def _build_header(pvr_data, tex, px, w, h, gbix=None, gitrim=False):
        pad = (-len(pvr_data)) % 4
        pvr_data += b"\x00" * pad

        px_id  = _ENC_PX_IDS.get(px,  1)
        tex_id = _ENC_TEX_IDS.get(tex, 1)
        pvr_sz = len(pvr_data) + 8

        hdr = bytearray(
            b"PVRT" +
            pvr_sz.to_bytes(4, "little") +
            bytes([px_id, tex_id, 0, 0]) +
            w.to_bytes(2, "little") +
            h.to_bytes(2, "little")
        )

        if gbix is not None:
            gbix = min(int(gbix), 0xFFFFFFFF)
            gh = bytearray(
                b"GBIX" +
                (4 if gitrim else 8).to_bytes(4, "little") +
                gbix.to_bytes(4, "little")
            )
            if not gitrim:
                gh += b"\x00" * 4
            hdr = gh + hdr

        return bytes(hdr) + pvr_data

    # public API 

    def from_array(self, rgba, tex_mode="auto", px_mode="auto",
                   gbix=None, gitrim=False, with_mipmaps=False,
                   vq_iter=10, vq_seed=2, pvpbank=0):
        """
        Encode rgba[H,W,4] uint8 → (pvr_bytes, pvp_bytes | None).

        Parameters
        ----------
        rgba        : np.ndarray, shape (H, W, 4), dtype uint8, top-down
        tex_mode    : str  e.g. "tw", "vq", "twre", "re", "st", "pal4",
                          "pal8", "svq", "bmp", "twal", or "auto"
        px_mode     : str  e.g. "565", "1555", "4444", "8888", "yuv422",
                          "bump", "yuv420", or "auto"
        gbix        : int or None — include GBIX header with this value
        gitrim      : bool — use short 4-byte GBIX header
        with_mipmaps: bool — append mipmap suffix to tex_mode when applicable
        vq_iter     : int  — K-means iterations for VQ / palette quantisation
        vq_seed     : int  — random seed for K-means reproducibility
        pvpbank     : int  — palette bank index written into the .pvp header
        """
        h, w = rgba.shape[:2]
        sq, rec, st, yuv = self._size_flags(w, h)

        # resolve "auto"
        if tex_mode == "auto" or px_mode == "auto":
            at, ap = self._auto_format(rgba, sq, rec, st, yuv)
            if tex_mode == "auto":
                tex_mode = at or "tw"
            if px_mode == "auto":
                px_mode  = ap or "565"

        # append mm suffix when mipmaps requested and mode supports it
        MM_CAPABLE = {"tw", "vq", "svq", "pal4", "pal8", "bmp", "twal"}
        if with_mipmaps and "mm" not in tex_mode and tex_mode in MM_CAPABLE and sq:
            tex_mode = tex_mode + " mm"

        if not _enc_is_compatible(tex_mode, px_mode):
            raise ValueError(f"Incompatible: tex={tex_mode}  px={px_mode}")
        if w > 1024 or h > 1024:
            raise ValueError("Image exceeds 1024×1024 limit")

        result = self._encode_pixels(rgba, w, h, tex_mode, px_mode,
                                     vq_iter, vq_seed)

        if isinstance(result, tuple):
            pvr_data, palette = result
            n_colors  = 16 if "pal4" in tex_mode else 256
            pvp_bytes = self._build_pvp(palette, n_colors, px_mode, pvpbank)
        else:
            pvr_data  = result
            pvp_bytes = None

        pvr_bytes = self._build_header(pvr_data, tex_mode, px_mode,
                                       w, h, gbix, gitrim)
        return pvr_bytes, pvp_bytes

    def from_file(self, filepath, tex_mode="auto", px_mode="auto",
                  gbix=None, gitrim=False, with_mipmaps=False,
                  vq_iter=10, vq_seed=2, pvpbank=0):
        """
        Load *filepath* via PIL and encode to (pvr_bytes, pvp_bytes | None).
        All parameters are the same as from_array().
        """
        rgba, w, h = load_image_as_rgba(filepath)
        return self.from_array(rgba, tex_mode=tex_mode, px_mode=px_mode,
                               gbix=gbix, gitrim=gitrim,
                               with_mipmaps=with_mipmaps,
                               vq_iter=vq_iter, vq_seed=vq_seed,
                               pvpbank=pvpbank)
