import tensorflow as tf

from model import Model, Modes


def _conv_filter(input_, k_size=5, stddev=0.02):
  w_t = tf.get_variable('w', [k_size, 1, input_.get_shape()[-1], 1])
  conv = tf.nn.depthwise_conv2d(input_, w_t, strides=[1, 1, 1, 1], padding='SAME')
  biases = tf.get_variable('biases', [input_.get_shape()[-1]], initializer=tf.constant_initializer(0.0))
  conv = tf.reshape(tf.nn.bias_add(conv, biases), conv.get_shape())
  
  return conv


class VocoderGAN(Model):
  audio_fs = 22050
  subseq_len = 24
  zdim = 100
  dim = 64
  stride = 2
  kernel_len = 25
  phaseshuffle_rad = 0
  wgangp_lambda = 10
  wgangp_nupdates = 5
  gen_nonlin = 'relu6'
  gan_strategy = 'wgangp'
  recon_loss_type = 'spec' # wav, spec
  recon_objective = 'l1' # l1, l2
  discriminator_type = "patched" # patched, regular
  recon_regularizer = 1. 
  train_batch_size = 64
  eval_batch_size = 1
  use_adversarial = True #Train as a GAN or not
  gen_filter_all = False
  gen_filter_last = False

  def build_generator(self, x_spec, z_tiled):
    x_spec = tf.transpose(x_spec, [0, 1, 3, 2])
    conv1d_transpose = lambda x, n: tf.layers.conv2d_transpose(
        x,
        n,
        (self.kernel_len, 1),
        strides=(self.stride, 1),
        padding='same')
    
    # same as conv1x1d
    conv1x1d_transpose = lambda x, n: tf.layers.conv2d_transpose(
        x,
        n,
        (1, 1),
        strides=(1, 1),
        padding='same')

    if self.gen_filter_all:
      conv_filter = lambda x, k: _conv_filter(x, k)
    else:
      conv_filter = lambda x, k: x

    if self.gen_filter_all or self.gen_filter_last:
      conv_filter_last = lambda x, k: _conv_filter(x, k)
    else:
      conv_filter_last = lambda x, k: x

    if self.gen_nonlin == 'relu':
      nonlin = lambda x: tf.nn.relu(x)
    elif self.gen_nonlin == 'linear':
      nonlin = lambda x: x
    elif self.gen_nonlin == 'relu6':
      nonlin = lambda x: tf.nn.relu6(x)
    else:
      raise ValueError()

    print("Building Generator")
    x = tf.concat([x_spec, z_tiled], axis=3)
    print(x)
    # [64, 80 + z_dim] -> [64, 256]
    with tf.variable_scope('upconv_1x1'):
      x = conv1x1d_transpose(x, self.dim * 4)
    x = nonlin(x)
    print(x)
    
    # [64, 256] -> [128, 128]
    with tf.variable_scope('upconv_1'):
      x = conv1d_transpose(x, self.dim * 2)
      x = conv_filter(x, 4)
    x = nonlin(x)
    print(x)
    # Layer 2
    # [128, 128] -> [256, 128]
    with tf.variable_scope('upconv_2'):
      x = conv1d_transpose(x, self.dim * 2)
      x = conv_filter(x, 8)
    x = nonlin(x)
    print(x)
    # Layer 3
    # [256, 128] -> [512, 64]
    with tf.variable_scope('upconv_3'):
      x = conv1d_transpose(x, self.dim)
      x = conv_filter(x, 16)
    x = nonlin(x)
    print(x)
    # Layer 4
    # [512, 64] -> [1024, 64]
    with tf.variable_scope('upconv_4'):
      x = conv1d_transpose(x, self.dim)
      x = conv_filter(x, 32)
    # [1024, 64] -> [2048, 32]
    with tf.variable_scope('upconv_5'):
      x = conv1d_transpose(x, int(self.dim/2))
      x = conv_filter(x, 64)
    x = nonlin(x)
    print(x)
    # [2048, 32] -> [4096, 32]
    with tf.variable_scope('upconv_6'):
      x = conv1d_transpose(x, int(self.dim/2))
      x = conv_filter(x, 128)
    x = nonlin(x)
    print(x)

    # [4096, 32] -> [8192, 16]
    with tf.variable_scope('upconv_7'):
      x = conv1d_transpose(x, int(self.dim/4))
      x = conv_filter(x, 256)
    x = nonlin(x)
    print(x)

    # [8192, 16] -> [16384, 1]
    with tf.variable_scope('upconv_8'):
      x = conv1d_transpose(x, 1)

    print(x)

    x = conv_filter_last(x, 512)
    x = tf.nn.tanh(x)
    print(x)

    return x

  def build_discriminator(self, x):
    conv1d = lambda x, n: tf.layers.conv2d(
        x,
        n,
        (self.kernel_len, 1),
        strides=(self.stride, 1),
        padding='same')

    conv1x1d = lambda x, n: tf.layers.conv2d(
        x,
        n,
        (1, 1),
        strides=(1, 1),
        padding='same')

    def lrelu(inputs, alpha=0.2):
      return tf.maximum(alpha * inputs, inputs)

    def apply_phaseshuffle(x, rad, pad_type='reflect'):
      if rad == 0:
        return x

      b, x_len, _, nch = x.get_shape().as_list()

      phase = tf.random_uniform([], minval=-rad, maxval=rad + 1, dtype=tf.int32)
      pad_l = tf.maximum(phase, 0)
      pad_r = tf.maximum(-phase, 0)
      phase_start = pad_r
      x = tf.pad(x, [[0, 0], [pad_l, pad_r], [0, 0], [0, 0]], mode=pad_type)

      x = x[:, phase_start:phase_start+x_len]
      x.set_shape([b, x_len, 1, nch])

      return x

    batch_size = tf.shape(x)[0]

    phaseshuffle = lambda x: apply_phaseshuffle(x, self.phaseshuffle_rad)

    # Layer 0
    # [16384, 1] -> [8192, 16]
    print("Building Discriminator")
    output = x
    print(output)

    with tf.variable_scope('downconv_0'):
      output = conv1d(output, int(self.dim/4))
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # Layer 1
    # [8192, 16] -> [4096, 32]
    with tf.variable_scope('downconv_1'):
      output = conv1d(output, int(self.dim/2))
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # Layer 2
    # [4096, 32] -> [2048, 32]
    with tf.variable_scope('downconv_2'):
      output = conv1d(output, int(self.dim/2))
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # Layer 3
    # [2048, 32] --> [1024, 64]
    with tf.variable_scope('downconv_3'):
      output = conv1d(output, self.dim)
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # [1024, 64] -> [512, 64]
    with tf.variable_scope('downconv_4'):
      output = conv1d(output, self.dim)
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # [512, 64] -> [256, 128]
    with tf.variable_scope('downconv_5'):
      output = conv1d(output, self.dim * 2)
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    # [256, 128] -> [128, 128]
    with tf.variable_scope('downconv_6'):
      output = conv1d(output, self.dim * 2)
    output = lrelu(output)
    output = phaseshuffle(output)
    print(output)

    if self.discriminator_type == "patched":
      output = conv1x1d(output, 1)
      print(output)

      return output[:,:,0,0]

    elif self.discriminator_type == "regular":
      # apply phase shuffle to the previous downconv

      # [128, 128] -> [64, 256]
      output = phaseshuffle(output)
      with tf.variable_scope('downconv_7'):
        output = conv1d(output, self.dim * 4)
      output = lrelu(output)
      print(output)

      # Flatten
      output = tf.reshape(output, [batch_size, self.subseq_len * self.dim * 4])
      print(output)

      # Connect to single logit
      with tf.variable_scope('output'):
        output = tf.layers.dense(output, 1)[:, 0]
      
      print(output)
      
      return output
    else:
      raise NotImplementedError()


  def __call__(self, x_wav, x_spec):
    try:
      batch_size = int(x_wav.get_shape()[0])
    except:
      batch_size = tf.shape(x_wav)[0]

    # Noise var
    z = tf.random.normal([batch_size, 1, 1, self.zdim], dtype=tf.float32)
    z_tiled = z * tf.constant(1.0, shape=[batch_size, self.subseq_len, 1, self.zdim])

    # Generator
    with tf.variable_scope('G'):
      G_z = self.build_generator(x_spec, z_tiled)
    G_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='G')

    # Discriminators
    with tf.name_scope('D_x'), tf.variable_scope('D'):
      D_x = self.build_discriminator(x_wav)
    with tf.name_scope('D_G_z'), tf.variable_scope('D', reuse=True):
      D_G_z = self.build_discriminator(G_z)
    D_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='D')

    self.wav_l1 = wav_l1 = tf.reduce_mean(tf.abs(x_wav - G_z))
    self.wav_l2 = wav_l2 = tf.reduce_mean(tf.square(x_wav - G_z))

    gen_spec = tf.contrib.signal.stft(G_z[:,:,0,0], 1024, 256, pad_end=True)
    gen_spec_mag = tf.abs(gen_spec)

    target_spec = tf.contrib.signal.stft(x_wav[:,:,0,0], 1024, 256, pad_end=True)
    target_spec_mag = tf.abs(target_spec)

    self.spec_l1 = spec_l1 = tf.reduce_mean(tf.abs(target_spec_mag - gen_spec_mag))
    self.spec_l2 = spec_l2 = tf.reduce_mean(tf.square(target_spec_mag - gen_spec_mag))

    
    if self.recon_objective == 'l1':
      if self.recon_loss_type == 'wav':
        self.recon_loss = wav_l1
      elif self.recon_loss_type == 'spec':
        self.recon_loss = spec_l1
    elif self.recon_objective == 'l2':
      if self.recon_loss_type == 'wav':
        self.recon_loss = wav_l2
      elif self.recon_loss_type == 'spec':
        self.recon_loss = spec_l2

    # WGAN-GP loss

    if self.gan_strategy == 'dcgan':
      fake = tf.zeros(D_x.shape, dtype=tf.float32)
      real = tf.ones(D_x.shape, dtype=tf.float32)

      G_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_G_z,
        labels=real
      ))

      D_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_G_z,
        labels=fake
      ))
      D_loss += tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(
        logits=D_x,
        labels=real
      ))

      D_loss /= 2.

    elif self.gan_strategy == 'wgangp':
      G_loss = -tf.reduce_mean(D_G_z)
      D_loss = tf.reduce_mean(D_G_z) - tf.reduce_mean(D_x)

      alpha = tf.random_uniform(shape=[batch_size, 1, 1, 1], minval=0., maxval=1.)
      differences = G_z - x_wav
      interpolates = x_wav + (alpha * differences)
      with tf.name_scope('D_interp'), tf.variable_scope('D', reuse=True):
        D_interp = self.build_discriminator(interpolates)

      gradients = tf.gradients(D_interp, [interpolates])[0]
      slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1, 2, 3]))
      gradient_penalty = tf.reduce_mean((slopes - 1.) ** 2.)
      D_loss += self.wgangp_lambda * gradient_penalty

    elif self.gan_strategy == 'lsgan':
      G_loss = tf.reduce_mean((D_G_z - 1.) ** 2)
      D_loss = tf.reduce_mean((D_x - 1.) ** 2)
      D_loss += tf.reduce_mean(D_G_z ** 2)
      D_loss /= 2.
    else:
      raise NotImplementedError()
    
    # adding the reconstruction LOSS
    if self.use_adversarial:
      G_loss_total = G_loss + self.recon_regularizer * self.recon_loss
    else:
      G_loss_total = self.recon_regularizer * self.recon_loss
    

    # Optimizers
    if self.gan_strategy == 'dcgan':
      G_opt = tf.train.AdamOptimizer(
          learning_rate=2e-4,
          beta1=0.5)
      D_opt = tf.train.AdamOptimizer(
          learning_rate=2e-4,
          beta1=0.5)
    elif self.gan_strategy == 'lsgan':
      G_opt = tf.train.RMSPropOptimizer(
          learning_rate=1e-4)
      D_opt = tf.train.RMSPropOptimizer(
          learning_rate=1e-4)
    elif self.gan_strategy == 'wgangp':
      G_opt = tf.train.AdamOptimizer(
          learning_rate=1e-4,
          beta1=0.5,
          beta2=0.9)
      D_opt = tf.train.AdamOptimizer(
          learning_rate=1e-4,
          beta1=0.5,
          beta2=0.9)

    # Training ops
    self.G_train_op = G_opt.minimize(G_loss_total, var_list=G_vars,
  global_step=tf.train.get_or_create_global_step())
    self.D_train_op = D_opt.minimize(D_loss, var_list=D_vars)

    # Summarize
    tf.summary.audio('x_wav', x_wav[:, :, 0, :], self.audio_fs)
    tf.summary.audio('G_z', G_z[:, :, 0, :], self.audio_fs)
    
    tf.summary.scalar('G_loss_total', G_loss_total)
    tf.summary.scalar('Recon_loss', self.recon_loss)
    tf.summary.scalar('spec_l2', spec_l2)
    tf.summary.scalar('wav_l1', wav_l1)

    if self.use_adversarial:
      tf.summary.scalar('G_loss', G_loss)
      tf.summary.scalar('D_loss', D_loss)


  def train_loop(self, sess):
    if self.use_adversarial:
      # Run Discriminator update only in adversarial scenario
      num_disc_updates = self.wgangp_nupdates if self.gan_strategy == 'wgangp' else 1
      for i in range(num_disc_updates):
        sess.run(self.D_train_op)
    sess.run(self.G_train_op)
    
